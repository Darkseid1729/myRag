"""
Custom test queries generated from actual inspection of testRepo1 and testRepo2.

testRepo1: Python + FastAPI computer vision system (OCR, detection, preprocessing)
testRepo2: React attendance management portal (teacher + student dashboards, biometric, QR)

Queries are grounded in REAL code that exists in these repos.
"""

import json
import numpy as np
from pathlib import Path
from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.intent.intent_router import IntentRouter
from src.retriever.hybrid_retriever import hybrid_search

def run_repo_tests():
    registry = ProjectRegistry()
    encoder = ONNXEncoder()
    router_inst = IntentRouter(encoder=encoder)

    # ----------------------------------------------------------------
    # testRepo2 queries — generated from actual code inspection
    # ----------------------------------------------------------------
    repo2_root = r"d:\backup(important)\myRag\testRepo2"

    # These queries are grounded in real entities observed:
    # - handleLogout() in TeacherDashboard.jsx
    # - MembersProvider + useMembers context
    # - LoginSwitcher.jsx + authApi.js for auth
    # - WebcamScanner.jsx for biometric/QR attendance
    # - QRGenerator.jsx + handleGenerate + handleGrantQRPermission
    # - attendanceApi.js: getCurrentAttendance, clearAttendance
    # - BiometricRegistration.jsx + scanBiometric
    # - DashboardContent + setActiveSubMenu for navigation
    # - Routes: "/" = LoginSwitcher, "/teacher-dashboard", "/student-dashboard"
    # - Timer.jsx (start/stop timer gates scanner)
    # - membersStorage.js: IndexedDB fallback for members

    repo2_queries = [
        # Intent: MODIFICATION_GUIDANCE — real function handleLogout exists
        "Where is the logout button and how does handleLogout work?",
        # Intent: SYMBOL_LOOKUP — loginTeacher in authApi.js
        "Where is loginTeacher defined?",
        # Intent: ARCHITECTURE — MembersContext + MembersProvider + useMembers
        "How does MembersContext provide data to child components?",
        # Intent: MODIFICATION_GUIDANCE — add to DashboardContent renderActiveComponent switch
        "How do I add a new panel to the teacher dashboard sidebar?",
        # Intent: SYMBOL_LOOKUP — scanBiometric in biometricApi.js, called from WebcamScanner
        "Where is scanBiometric called and what does it send to the backend?",
        # Intent: RERENDER_ANALYSIS — DashboardContent uses useEffect polling attendance every 5s
        "Why does DashboardContent re-render repeatedly?",
        # Intent: ROUTE_TRACING — App.jsx defines routes, LoginSwitcher is on "/"
        "Which components are rendered on the /teacher-dashboard route?",
        # Intent: IMPACT_ANALYSIS — removeMember in MembersProvider fetches fresh list from backend
        "What happens when removeMember is called?",
        # Intent: SYMBOL_LOOKUP — handleGrantQRPermission in QRGenerator
        "Where is QR access granted to a student?",
        # Intent: ARCHITECTURE — WebcamScanner scans QR + face, uses jsQR + BarcodeDetector
        "How does the webcam scanner detect both QR and face at the same time?",
        # Intent: DEBUGGING — attendanceStorage.js has markAttendance, called from WebcamScanner
        "Why might attendance not get marked when scanning a QR code?",
        # Intent: MODIFICATION_GUIDANCE — PasswordReset.jsx calls updateTeacherPassword from authApi
        "Where should I add student password reset functionality?",
    ]

    # ----------------------------------------------------------------
    # testRepo1 queries — generated from inspection
    # testRepo1 is a Python OCR + face detection system:
    # - detection.py: face detection, landmark detection
    # - ocr.py: OCR pipeline
    # - preprocessing.py: image preprocessing
    # - segmentation.py: image segmentation
    # - api.py: FastAPI endpoints
    # - main.py: main orchestrator
    # - utils.py: utility functions
    # NOTE: testRepo1 is Python, the RAG indexer targets JS/TS, so
    # we test against testRepo2 only (which is indexed).
    # ----------------------------------------------------------------

    results_out = []
    results_out.append("# Custom Test Query Results — testRepo2 (Attendance Portal)\n")
    results_out.append(
        "_Queries generated after direct code inspection of testRepo2. "
        "Each query is grounded in real functions, components, and routes found in the codebase._\n"
    )
    results_out.append("---\n")

    for i, query in enumerate(repo2_queries, 1):
        try:
            db = registry.get_or_create(repo2_root)
            decision = router_inst.route(query)
            decision.strategy.top_k = 5

            results = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
            db.close()

            results_out.append(f"## Query {i}: `{query}`")
            results_out.append(f"**Intent Detected:** {decision.intent.value} (Confidence: {decision.confidence:.2f})")
            results_out.append(f"**Expanded Query:** {decision.expanded_query}")
            results_out.append(f"**Strategy:** Lexical={decision.strategy.lexical_weight}, Semantic={decision.strategy.semantic_weight}, Graph={decision.strategy.graph_weight} (Depth: {decision.strategy.graph_depth})")
            results_out.append("**Top 5 Chunks Retrieved:**")

            if not results:
                results_out.append("- _No chunks found._")
            else:
                for j, r in enumerate(results, 1):
                    results_out.append(
                        f"{j}. **{r.file_path}:{r.start_line}** [{r.chunk_type}] — `{r.name or 'anonymous'}`"
                    )
                    results_out.append(
                        f"   - Score: **{r.final_score:.4f}** (Lex: {r.lexical_score:.4f} | Sem: {r.semantic_score:.4f} | Graph: {r.graph_score:.4f})"
                    )
                    snippet = r.text[:150].replace('\n', ' ').replace('\r', ' ')
                    results_out.append(f"   - Snippet: `{snippet}...`")

            results_out.append("")
            results_out.append("---")
            results_out.append("")

        except Exception as e:
            results_out.append(f"## Query {i}: `{query}` — **ERROR: {e}**\n")

    # ----------------------------------------------------------------
    # Write results
    # ----------------------------------------------------------------
    output_path = Path("detailed_query_result_my_testrepo.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(results_out))

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    run_repo_tests()
