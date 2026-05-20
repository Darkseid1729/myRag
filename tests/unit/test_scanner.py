"""Tests for file scanner."""

from pathlib import Path
import tempfile, os
from src.scanner.file_scanner import scan_project, _classify_file


def _make_project(tmp: str) -> Path:
    root = Path(tmp)
    (root / "src" / "components").mkdir(parents=True)
    (root / "src" / "hooks").mkdir(parents=True)
    (root / "node_modules" / "react").mkdir(parents=True)
    (root / "src" / "components" / "LoginForm.tsx").write_text("export const LoginForm = () => <div/>")
    (root / "src" / "hooks" / "useAuth.ts").write_text("export const useAuth = () => {}")
    (root / "node_modules" / "react" / "index.js").write_text("module.exports = {}")
    return root


def test_scan_finds_source_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_project(tmp)
        files = scan_project(str(root))
        paths = [f.path for f in files]
        assert any("LoginForm" in p for p in paths)
        assert any("useAuth" in p for p in paths)
        assert not any("node_modules" in p for p in paths)


def test_classify_hook():
    assert _classify_file("src/hooks/useAuth.ts", "useAuth") == "HOOK"


def test_classify_component():
    assert _classify_file("src/components/LoginForm.tsx", "LoginForm") in ("COMPONENT", "UTIL")
