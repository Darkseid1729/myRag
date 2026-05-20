# Pseudocode: Complete Indexing Pipeline

## indexing_pipeline.py

```
FUNCTION run_indexing(project_path, project_id, config):

    START_TIMER()
    db = open_sqlite(get_db_path(project_id))
    apply_migrations(db)

    # ── STEP 1: Scan files ─────────────────────────────────────────
    all_files = file_scanner.scan(
        root=project_path,
        include=["*.js", "*.jsx", "*.ts", "*.tsx"],
        exclude=["node_modules", "dist", ".next", "*.test.*", "*.spec.*"]
    )
    LOG(f"Found {len(all_files)} source files")

    # ── STEP 2: Detect changes (incremental mode) ──────────────────
    IF config.incremental AND project_already_indexed(project_id, db):
        changes = change_detector.detect(all_files, project_id, db)
        files_to_process = changes.new + changes.modified
        FOR deleted IN changes.deleted:
            delete_file_from_index(deleted.id, db)
        LOG(f"Incremental: {len(files_to_process)} files to reindex")
    ELSE:
        files_to_process = all_files
        LOG("Full reindex")

    IF len(files_to_process) == 0:
        RETURN IndexResponse(status="NO_CHANGES")

    # ── STEP 3: Parse files in parallel ───────────────────────────
    all_parse_results = []
    WITH ProcessPoolExecutor(max_workers=min(4, cpu_count())) AS pool:
        FOR file_info, parse_result IN pool.map(parse_single_file, files_to_process):
            IF parse_result.parse_error:
                LOG_WARNING(f"Parse error in {file_info.path}: {parse_result.parse_error}")
            all_parse_results.append((file_info, parse_result))

    # ── STEP 4: Extract metadata ────────────────────────────────────
    all_chunks = []
    FOR file_info, parse_result IN all_parse_results:

        # Save file record
        db.upsert_file(file_info)

        # Run all extractors (order matters: imports first for resolution)
        components = component_extractor.extract(parse_result)
        hooks = hook_extractor.extract(parse_result)
        functions = function_extractor.extract(parse_result)
        state_usages = state_extractor.extract(parse_result)
        context_usages = context_extractor.extract(parse_result)
        api_calls = api_call_extractor.extract(parse_result, file_info)

        # ── STEP 5: Chunk ─────────────────────────────────────────
        strategy = chunk_strategy.select(file_info.file_type)
        file_chunks = strategy.chunk(
            file_info=file_info,
            parse_result=parse_result,
            components=components,
            hooks=hooks,
            functions=functions
        )
        all_chunks.extend(file_chunks)

    LOG(f"Total chunks: {len(all_chunks)}")

    # ── STEP 6: Index all chunks ────────────────────────────────────
    # Run in parallel where possible

    WITH db.transaction():

        # 6a. Write chunks to DB
        FOR chunk IN all_chunks:
            db.upsert_chunk(chunk)

        # 6b. Lexical index (FTS5)
        lexical_indexer.index(all_chunks, db)

        # 6c. Symbol index
        symbol_indexer.index(all_chunks, db)

    # 6d. Embeddings (separate transaction — can be slow)
    encoder = get_encoder()  # Singleton ONNX
    FOR batch IN batches(all_chunks, size=16):
        texts = [c.fts_tokens or c.text[:4096] for c in batch]
        vectors = encoder.encode(texts)           # (16, 384) float32
        quantized = [quantize_int8(v) for v in vectors]
        WITH db.transaction():
            FOR chunk, (qvec, scale) IN zip(batch, quantized):
                db.upsert_embedding(chunk.id, qvec, scale)

    # 6e. Graph (must come after all chunks are written)
    graph_builder.build(all_chunks, all_parse_results, db)

    # ── STEP 7: Update metadata ────────────────────────────────────
    db.execute("""
        INSERT OR REPLACE INTO indexing_metadata VALUES
        ('file_count', ?),
        ('chunk_count', ?),
        ('indexed_at', ?)
    """, [len(files_to_process), len(all_chunks), int(time.time())])

    ELAPSED = STOP_TIMER()
    RETURN IndexResponse(
        project_id=project_id,
        file_count=len(files_to_process),
        chunk_count=len(all_chunks),
        duration_ms=ELAPSED,
        status="COMPLETE"
    )
```

---

## parse_single_file.py

```
FUNCTION parse_single_file(file_info: FileInfo) -> (FileInfo, ParseResult):

    TRY:
        content = read_file(file_info.path, encoding="utf-8")

        # Primary parser: Tree-sitter
        TRY:
            parse_result = tree_sitter_parser.parse(content, file_info.path)
        CATCH TreeSitterError AS e:
            LOG_WARNING(f"Tree-sitter failed: {e}, trying Babel fallback")
            parse_result = babel_bridge.parse(content, file_info.path)

        RETURN (file_info, parse_result)

    CATCH (FileNotFoundError, PermissionError) AS e:
        RETURN (file_info, ParseResult(parse_error=str(e)))
    CATCH UnicodeDecodeError:
        # Try with latin-1 encoding
        content = read_file(file_info.path, encoding="latin-1")
        parse_result = tree_sitter_parser.parse(content, file_info.path)
        RETURN (file_info, parse_result)
```

---

## chunk_strategy.py

```
FUNCTION select_strategy(file_type: FileType) -> ChunkerBase:
    MATCH file_type:
        CASE COMPONENT → return ComponentChunker()
        CASE HOOK      → return HookChunker()
        CASE PAGE      → return ComponentChunker()  # Same as component
        CASE ROUTE     → return RouteChunker()
        CASE CONTEXT   → return ComponentChunker()  # Context files have components too
        CASE STORE     → return FunctionChunker()
        CASE UTIL      → return FunctionChunker()
        DEFAULT        → return SlidingWindowChunker(window=40, overlap=10)


FUNCTION ComponentChunker.chunk(file_info, parse_result, ...):
    chunks = []

    # Always add import block first
    IF parse_result.imports:
        import_chunk = make_import_chunk(file_info, parse_result.imports)
        chunks.append(import_chunk)

    # Add each component as its own chunk
    FOR component IN parse_result.components:
        chunk = Chunk(
            id=generate_chunk_id(file_info.path, component.start_line, component.name),
            file_id=file_info.id,
            chunk_type=ChunkType.COMPONENT,
            name=component.name,
            text=slice_text(file_info.content, component.start_line, component.end_line),
            start_line=component.start_line,
            end_line=component.end_line,
            symbols=[component.name] + component.hooks_used,
            hooks_used=component.hooks_used,
            has_state=component.has_state,
            has_jsx=True,
            summary=rule_based_summary(component)
        )
        chunk.fts_tokens = normalize_for_fts(chunk.text + " " + " ".join(chunk.symbols))
        chunks.append(chunk)

    # Add state blocks as separate fine-grained chunks
    FOR state IN parse_result.state_usages:
        IF state.start_line > 0:
            state_chunk = make_state_chunk(file_info, state)
            chunks.append(state_chunk)

    # Add helper functions
    FOR func IN parse_result.functions:
        IF func.start_line not_in any_existing_chunk_range(chunks):
            func_chunk = make_function_chunk(file_info, func)
            chunks.append(func_chunk)

    # Enforce max chunks per file
    IF len(chunks) > config.max_chunks_per_file:
        # Keep highest-priority chunk types
        chunks = prioritize_chunks(chunks, max=config.max_chunks_per_file)

    RETURN chunks
```

---

## hybrid_retriever.py

```
ASYNC FUNCTION retrieve(query, project_id, config):

    db = get_db(project_id)

    # Route intent
    routing = intent_router.route(query)
    strategy = routing.strategy
    expanded = routing.expanded_query

    # Check cache first
    cached = retrieval_cache.get(query, project_id, routing.intent)
    IF cached AND NOT config.bypass_cache:
        RETURN cached

    # Parallel retrieval
    ASYNC WITH TaskGroup() AS tg:
        lex_task   = tg.create_task(lexical_retrieve(expanded, db, top_k=50))
        graph_task = tg.create_task(dummy_task())  # placeholder

    lex_scores = await lex_task  # {chunk_id: score}

    # Semantic (sequential, needs lex candidates)
    candidate_ids = list(lex_scores.keys())[:50]
    sem_scores = await semantic_retrieve(expanded, candidate_ids, db)

    # Graph (uses top lex results as seeds)
    seeds = sorted(lex_scores, key=lex_scores.get, reverse=True)[:10]
    graph_scores = await graph_retrieve(seeds, strategy, db)

    # Fuse scores
    fused = fuse_scores(lex_scores, sem_scores, graph_scores, strategy)

    # Sort
    sorted_ids = sorted(fused, key=fused.get, reverse=True)[:strategy.top_k]

    # Fetch chunk data
    chunks = db.fetch_chunks_by_ids(sorted_ids)

    # Build ranked list
    ranked = [
        RankedChunk(
            chunk=chunk,
            lex_score=lex_scores.get(chunk.id, 0.0),
            sem_score=sem_scores.get(chunk.id, 0.0),
            graph_score=graph_scores.get(chunk.id, 0.0),
            final_score=fused[chunk.id]
        )
        FOR chunk IN chunks
    ]

    # Deduplicate overlapping ranges
    ranked = deduplicate_ranges(ranked)

    # Optional reranking
    IF config.enable_reranker AND len(ranked) > 1:
        ranked = reranker.rerank(query, ranked)

    # Cache result
    retrieval_cache.set(query, project_id, routing.intent, ranked)

    RETURN ranked
```
