import json
import numpy as np
from pathlib import Path
from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.intent.intent_router import IntentRouter
from src.retriever.hybrid_retriever import hybrid_search

def run_tests():
    registry = ProjectRegistry()
    encoder = ONNXEncoder()
    router_inst = IntentRouter(encoder=encoder)
    
    project_root = r"d:\backup(important)\myRag\testRepo2"
    
    queries = [
        "Add a logout feature",
        "Where is authentication handled?",
        "Find all places using useTheme",
        "Add a calendar to keep notes from the sidebar",
        "Why does Dashboard rerender?",
        "Which files affect this route?",
    ]

    results_out = []
    
    for query in queries:
        try:
            db = registry.get_or_create(project_root)
            decision = router_inst.route(query)
            decision.strategy.top_k = 5
            
            # Run hybrid search
            results = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
            db.close()
            
            results_out.append(f"### Query: `{query}`")
            results_out.append(f"**Intent Detected:** {decision.intent.value} (Confidence: {decision.confidence:.2f})")
            results_out.append(f"**Expanded Query:** {decision.expanded_query}")
            results_out.append(f"**Strategy Used:** Lexical={decision.strategy.lexical_weight}, Semantic={decision.strategy.semantic_weight}, Graph={decision.strategy.graph_weight} (Depth: {decision.strategy.graph_depth})")
            results_out.append("**Top 5 Chunks Retrieved:**")
            
            if not results:
                results_out.append("- *No chunks found.*")
            
            for i, r in enumerate(results, 1):
                results_out.append(f"{i}. **{r.file_path}:{r.start_line}** [{r.chunk_type}]")
                results_out.append(f"   - Final Score: {r.final_score:.4f} (Lexical: {r.lexical_score:.4f} | Semantic: {r.semantic_score:.4f} | Graph: {r.graph_score:.4f})")
                snippet = r.text[:120].replace('\n', ' ')
                results_out.append(f"   - Snippet: `{snippet}...`")
            results_out.append("\n" + "-"*50 + "\n")
        except Exception as e:
            results_out.append(f"### Query: `{query}` (ERROR: {e})\n")
            
    with open("detailed_query_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(results_out))

if __name__ == "__main__":
    run_tests()
