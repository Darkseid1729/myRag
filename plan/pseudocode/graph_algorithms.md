# Pseudocode: Graph Engine Algorithms

## graph_builder.py

```
FUNCTION build_graph(all_chunks, all_parse_results, db):

    # Build lookup: file_path → file_id, function_name → chunk_id
    path_to_file_id = {f.path: f.id FOR f, _ IN all_parse_results}
    name_to_chunk_id = {c.name: c.id FOR c IN all_chunks IF c.name}

    edges = []

    FOR file_info, parse_result IN all_parse_results:

        # ── Import edges (file → file) ──────────────────────────
        FOR imp IN parse_result.imports:
            IF imp.resolved_path AND imp.resolved_path IN path_to_file_id:
                edges.append(GraphEdge(
                    from_id=file_info.id,
                    to_id=path_to_file_id[imp.resolved_path],
                    edge_type=EdgeType.IMPORTS
                ))

        FOR chunk IN get_chunks_for_file(file_info.id, all_chunks):

            # ── Call edges (function → function) ────────────────
            FOR called_name IN chunk.function_calls:
                IF called_name IN name_to_chunk_id:
                    edges.append(GraphEdge(
                        from_id=chunk.id,
                        to_id=name_to_chunk_id[called_name],
                        edge_type=EdgeType.CALLS
                    ))

            # ── Hook usage edges (component → hook) ─────────────
            FOR hook_name IN chunk.hooks_used:
                IF hook_name IN name_to_chunk_id:  # Custom hooks only
                    edges.append(GraphEdge(
                        from_id=chunk.id,
                        to_id=name_to_chunk_id[hook_name],
                        edge_type=EdgeType.USES_HOOK
                    ))

            # ── Renders edges (component → component) ────────────
            IF chunk.chunk_type == ChunkType.COMPONENT:
                FOR rendered IN extract_rendered_components(chunk.text):
                    IF rendered IN name_to_chunk_id:
                        edges.append(GraphEdge(
                            from_id=chunk.id,
                            to_id=name_to_chunk_id[rendered],
                            edge_type=EdgeType.RENDERS
                        ))

            # ── Context edges ────────────────────────────────────
            FOR ctx IN parse_result.context_usages:
                IF ctx.usage_type == "PROVIDES":
                    edges.append(GraphEdge(
                        from_id=chunk.id,
                        to_id=ctx.context_name,  # virtual node
                        edge_type=EdgeType.PROVIDES_CONTEXT
                    ))
                ELIF ctx.usage_type == "CONSUMES":
                    edges.append(GraphEdge(
                        from_id=chunk.id,
                        to_id=ctx.context_name,
                        edge_type=EdgeType.CONSUMES_CONTEXT
                    ))

    # Bulk insert edges
    WITH db.transaction():
        db.executemany(
            "INSERT OR IGNORE INTO graph_edges(from_id, to_id, edge_type) VALUES (?,?,?)",
            [(e.from_id, e.to_id, e.edge_type.value) FOR e IN edges]
        )

    LOG(f"Built {len(edges)} graph edges")
```

---

## graph_traversal.py

```
FUNCTION bfs(start_id, edge_types, max_depth, reverse=False, db):
    """
    Breadth-first traversal of the code graph.
    reverse=True: traverse incoming edges (impact analysis)
    reverse=False: traverse outgoing edges (dependency tracing)
    """

    visited = {start_id}
    queue = deque([(start_id, 0, [start_id])])
    results = []

    WHILE queue:
        node_id, depth, path = queue.popleft()

        IF depth >= max_depth:
            CONTINUE

        # Get neighbors
        IF NOT reverse:
            sql = "SELECT to_id, edge_type FROM graph_edges WHERE from_id=? AND edge_type IN ({placeholders})"
            rows = db.execute(sql, [node_id] + edge_types)
            neighbors = [(row.to_id, row.edge_type) FOR row IN rows]
        ELSE:
            sql = "SELECT from_id, edge_type FROM graph_edges WHERE to_id=? AND edge_type IN ({placeholders})"
            rows = db.execute(sql, [node_id] + edge_types)
            neighbors = [(row.from_id, row.edge_type) FOR row IN rows]

        FOR neighbor_id, edge_type IN neighbors:
            IF neighbor_id NOT IN visited:
                visited.add(neighbor_id)
                new_path = path + [neighbor_id]
                results.append(TraversalNode(
                    node_id=neighbor_id,
                    depth=depth + 1,
                    path=new_path,
                    edge_type=EdgeType(edge_type)
                ))
                queue.append((neighbor_id, depth + 1, new_path))

    RETURN results


FUNCTION shortest_path_length(source_id, target_id, db, max_depth=5):
    """
    Find shortest path between two nodes using bidirectional BFS.
    Returns depth or None if unreachable within max_depth.
    """

    # Forward BFS from source
    forward_visited = {source_id: 0}
    forward_queue = deque([(source_id, 0)])

    # Backward BFS from target
    backward_visited = {target_id: 0}
    backward_queue = deque([(target_id, 0)])

    FOR depth IN range(max_depth):
        # Expand forward frontier
        FOR _ IN range(len(forward_queue)):
            node, d = forward_queue.popleft()
            IF d == depth:
                FOR neighbor IN get_outgoing(node, db):
                    IF neighbor NOT IN forward_visited:
                        forward_visited[neighbor] = d + 1
                        forward_queue.append((neighbor, d + 1))
                        IF neighbor IN backward_visited:
                            RETURN d + 1 + backward_visited[neighbor]

        # Expand backward frontier
        FOR _ IN range(len(backward_queue)):
            node, d = backward_queue.popleft()
            IF d == depth:
                FOR neighbor IN get_incoming(node, db):
                    IF neighbor NOT IN backward_visited:
                        backward_visited[neighbor] = d + 1
                        backward_queue.append((neighbor, d + 1))
                        IF neighbor IN forward_visited:
                            RETURN d + 1 + forward_visited[neighbor]

    RETURN None  # Unreachable within max_depth
```

---

## impact_analyzer.py

```
FUNCTION analyze_impact(chunk_id, max_depth=3, db):
    """
    Answer: "What would break if I changed this chunk?"
    Uses reverse BFS to find all dependents.
    """

    all_edge_types = [e.value FOR e IN EdgeType]  # All edge types

    # Who imports this chunk's file?
    file_id = get_file_id_for_chunk(chunk_id, db)
    file_importers = bfs(
        start_id=file_id,
        edge_types=[EdgeType.IMPORTS.value],
        max_depth=max_depth,
        reverse=True,
        db=db
    )

    # Who calls this chunk?
    direct_callers = bfs(
        start_id=chunk_id,
        edge_types=[EdgeType.CALLS.value],
        max_depth=1,
        reverse=True,
        db=db
    )

    # Who uses this hook (if it's a hook)?
    hook_consumers = []
    IF is_hook(chunk_id, db):
        hook_consumers = bfs(
            start_id=chunk_id,
            edge_types=[EdgeType.USES_HOOK.value],
            max_depth=1,
            reverse=True,
            db=db
        )

    # Who consumes this context (if it's a provider)?
    context_consumers = []
    IF provides_context(chunk_id, db):
        context_name = get_provided_context(chunk_id, db)
        context_consumers = get_context_consumers(context_name, db)

    # Combine and deduplicate
    all_affected = deduplicate_traversal_nodes(
        file_importers + direct_callers + hook_consumers + context_consumers
    )

    RETURN ImpactReport(
        root_chunk_id=chunk_id,
        direct_dependents=filter_depth(all_affected, max_depth=1),
        context_consumers=context_consumers,
        all_affected=all_affected
    )
```

---

## dependency_tracer.py

```
FUNCTION trace_dependencies(chunk_id, max_depth=3, db):
    """
    Answer: "What does this chunk depend on?"
    """

    # What does this chunk import (via file)?
    file_id = get_file_id_for_chunk(chunk_id, db)
    imported_files = bfs(
        start_id=file_id,
        edge_types=[EdgeType.IMPORTS.value],
        max_depth=max_depth,
        reverse=False,
        db=db
    )

    # What functions does this call?
    called_chunks = bfs(
        start_id=chunk_id,
        edge_types=[EdgeType.CALLS.value],
        max_depth=2,
        reverse=False,
        db=db
    )

    # What hooks does this use?
    used_hooks = bfs(
        start_id=chunk_id,
        edge_types=[EdgeType.USES_HOOK.value],
        max_depth=1,
        reverse=False,
        db=db
    )

    # What contexts does this consume?
    consumed_contexts = bfs(
        start_id=chunk_id,
        edge_types=[EdgeType.CONSUMES_CONTEXT.value],
        max_depth=1,
        reverse=False,
        db=db
    )

    RETURN DependencyReport(
        root_chunk_id=chunk_id,
        direct_imports=imported_files,
        hooks_used=used_hooks,
        context_consumed=consumed_contexts,
        state_managed=[],  # Populated separately from state_usages
        transitive_deps=imported_files + called_chunks
    )
```
