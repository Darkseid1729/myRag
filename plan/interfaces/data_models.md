# Interfaces: Core Data Models
# TypeScript-style interface definitions for all system entities

# ============================================================
# FILE SYSTEM LAYER
# ============================================================

interface FileInfo:
    id: str                     # SHA-1 of normalized path
    path: str                   # Absolute path
    relative_path: str          # Relative to project root
    file_type: FileType         # COMPONENT | HOOK | ROUTE | PAGE | UTIL | CONTEXT | STORE | CONFIG
    size_bytes: int
    line_count: int
    content_hash: str           # SHA-256 of file bytes
    modified_at: float          # Unix timestamp
    indexed_at: float

enum FileType:
    COMPONENT
    HOOK
    ROUTE
    PAGE
    UTIL
    CONTEXT
    STORE
    CONFIG
    UNKNOWN

# ============================================================
# PARSING LAYER
# ============================================================

interface ParseResult:
    file_id: str
    imports: List[ImportRecord]
    exports: List[ExportRecord]
    components: List[ComponentMeta]
    hooks: List[HookMeta]
    functions: List[FunctionMeta]
    state_usages: List[StateUsage]
    context_usages: List[ContextUsage]
    api_calls: List[ApiCallMeta]
    event_handlers: List[EventHandlerMeta]
    node_ranges: Dict[str, Tuple[int, int]]  # name → (start_line, end_line)
    parse_error: Optional[str]

interface ImportRecord:
    source: str                 # import path (e.g., '../hooks/useAuth')
    specifiers: List[str]       # imported names
    is_default: bool
    is_namespace: bool
    resolved_path: Optional[str]  # absolute resolved path
    is_external: bool           # True for node_modules

interface ExportRecord:
    name: str
    is_default: bool
    export_type: str            # FUNCTION | CLASS | CONST | RE_EXPORT

interface ComponentMeta:
    name: str
    start_line: int
    end_line: int
    is_default_export: bool
    props: List[str]
    hooks_used: List[str]
    renders: List[str]          # component names in JSX tree
    has_state: bool
    has_effects: bool
    is_class_component: bool

interface HookMeta:
    name: str
    start_line: int
    end_line: int
    uses_hooks: List[str]       # other hooks called inside
    returns: Optional[str]      # inferred return type description
    has_state: bool
    has_effects: bool

interface FunctionMeta:
    name: str
    start_line: int
    end_line: int
    is_async: bool
    is_exported: bool
    calls: List[str]            # function names called inside
    has_api_call: bool
    parameters: List[str]

interface StateUsage:
    variable_name: str
    setter_name: Optional[str]
    initial_value: Optional[str]
    state_type: str             # USESTATE | USEREDUCER | REDUX | ZUSTAND | JOTAI | RECOIL | USEREF
    chunk_id: Optional[str]

interface ContextUsage:
    context_name: str
    usage_type: str             # CREATES | PROVIDES | CONSUMES
    chunk_id: Optional[str]

interface ApiCallMeta:
    method: Optional[str]       # GET | POST | PUT | DELETE | PATCH | null (if dynamic)
    endpoint: Optional[str]
    client_type: str            # FETCH | AXIOS | REACT_QUERY | CUSTOM
    is_dynamic: bool

interface EventHandlerMeta:
    event_type: str             # click | change | submit | etc.
    handler_name: str
    is_inline: bool             # True for onClick={()=>...}

# ============================================================
# CHUNKING LAYER
# ============================================================

interface Chunk:
    id: str                     # SHA-1 of (file_id + start_line + name)
    file_id: str
    file_path: str
    file_type: FileType
    chunk_type: ChunkType
    name: str
    text: str                   # Raw source code
    start_line: int
    end_line: int
    char_count: int
    symbols: List[str]          # Defined identifiers
    imports: List[str]          # Referenced external identifiers
    hooks_used: List[str]
    has_state: bool
    has_jsx: bool
    has_api_call: bool
    has_context: bool
    summary: Optional[str]
    fts_tokens: Optional[str]   # Pre-normalized text for FTS
    metadata: Optional[Dict]    # Extra plugin data
    created_at: float

enum ChunkType:
    COMPONENT
    HOOK
    FUNCTION
    ROUTE_BLOCK
    IMPORT_BLOCK
    CONTEXT_DEF
    STATE_BLOCK
    MISC

# ============================================================
# GRAPH LAYER
# ============================================================

interface GraphEdge:
    from_id: str
    to_id: str
    edge_type: EdgeType
    weight: float

enum EdgeType:
    IMPORTS           = 1
    CALLS             = 2
    USES_HOOK         = 3
    RENDERS           = 4
    PROVIDES_CONTEXT  = 5
    CONSUMES_CONTEXT  = 6
    MANAGES_STATE     = 7
    DEFINES_ROUTE     = 8
    USES_API          = 9

interface TraversalNode:
    node_id: str
    depth: int
    path: List[str]             # Ordered list of node IDs from root to this node
    edge_type: EdgeType         # Edge type used to reach this node

interface DependencyReport:
    root_chunk_id: str
    direct_imports: List[TraversalNode]
    hooks_used: List[TraversalNode]
    context_consumed: List[TraversalNode]
    state_managed: List[TraversalNode]
    transitive_deps: List[TraversalNode]

interface ImpactReport:
    root_chunk_id: str
    direct_dependents: List[TraversalNode]
    context_consumers: List[TraversalNode]
    all_affected: List[TraversalNode]

# ============================================================
# RETRIEVAL LAYER
# ============================================================

interface RetrievalStrategy:
    lexical_weight: float       # [0, 1]
    semantic_weight: float      # [0, 1]
    graph_weight: float         # [0, 1]
    graph_depth: int            # Max BFS depth
    edge_types: List[EdgeType]  # Which edge types to traverse
    reverse: bool               # Use reverse BFS for impact analysis
    top_k: int                  # Number of results to return
    use_graph: bool

interface LexicalResult:
    chunk_id: str
    raw_bm25: float
    normalized_score: float     # [0, 1]
    matched_terms: List[str]
    snippet: str

interface SemanticResult:
    chunk_id: str
    score: float                # Cosine similarity [0, 1]
    embedding_model: str

interface RankedChunk:
    chunk: Chunk
    lex_score: float
    sem_score: float
    graph_score: float
    final_score: float
    rerank_score: Optional[float]

# ============================================================
# INTENT LAYER
# ============================================================

enum Intent:
    SYMBOL_LOOKUP
    ARCHITECTURE
    MODIFICATION_GUIDANCE
    DEBUGGING
    RERENDER_ANALYSIS
    ROUTE_TRACING
    IMPACT_ANALYSIS

interface RoutingDecision:
    original_query: str
    expanded_query: str
    intent: Intent
    strategy: RetrievalStrategy
    confidence: float           # [0, 1]

# ============================================================
# CONTEXT / RESPONSE LAYER
# ============================================================

interface ChunkEvidence:
    chunk: Chunk
    summary: str
    relevance_score: float
    relationship_to_query: str
    dependencies: List[str]

interface EvidencePack:
    query: str
    intent: Intent
    chunks: List[ChunkEvidence]
    dependency_summary: str
    total_tokens: int
    confidence: float

interface QueryResponse:
    query: str
    intent: str
    answer: Optional[str]       # LLM-generated answer, or None
    retrieved_chunks: List[Dict]
    relationships: str
    confidence: float
    latency_ms: int
    from_cache: bool

# ============================================================
# API LAYER
# ============================================================

interface IndexRequest:
    project_path: str
    project_id: Optional[str]   # Auto-generated if not provided
    include_patterns: Optional[List[str]]
    exclude_patterns: Optional[List[str]]
    force_reindex: bool

interface IndexResponse:
    project_id: str
    file_count: int
    chunk_count: int
    embedding_count: int
    edge_count: int
    duration_ms: int
    status: str                 # COMPLETE | IN_PROGRESS | FAILED

interface QueryRequest:
    project_id: str
    query: str
    max_results: int            # Default: 10
    enable_llm: bool            # Default: True if LLM available
    llm_backend: Optional[str]  # ollama | llamacpp | openai
    stream: bool

interface StatusResponse:
    project_id: str
    indexed: bool
    file_count: int
    chunk_count: int
    last_indexed: Optional[str]
    ram_usage_mb: float
