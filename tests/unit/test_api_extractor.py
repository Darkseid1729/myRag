"""Unit tests for the API call extractor."""

import pytest
from src.extractor.api_extractor import extract_api_calls


class TestExtractApiCalls:
    def test_basic_fetch_get(self):
        src = "const data = await fetch('/api/users');"
        calls = extract_api_calls(src)
        assert any(c.endpoint == "/api/users" and c.method == "GET" for c in calls)

    def test_fetch_post(self):
        src = "await fetch('/api/login', { method: 'POST', body: JSON.stringify(creds) });"
        calls = extract_api_calls(src)
        assert any(c.endpoint == "/api/login" and c.method == "POST" for c in calls)

    def test_axios_get(self):
        src = "const res = await axios.get('/api/profile');"
        calls = extract_api_calls(src)
        assert any(c.endpoint == "/api/profile" and c.method == "GET" and c.client_type == "axios" for c in calls)

    def test_axios_post(self):
        src = "await axios.post('/api/create', payload);"
        calls = extract_api_calls(src)
        assert any(c.method == "POST" and c.client_type == "axios" for c in calls)

    def test_axios_delete(self):
        src = "await axios.delete('/api/items/42');"
        calls = extract_api_calls(src)
        assert any(c.method == "DELETE" for c in calls)

    def test_template_literal_fetch(self):
        src = "await fetch(`/api/users/${userId}`);"
        calls = extract_api_calls(src)
        assert any(c.is_dynamic for c in calls)

    def test_no_calls(self):
        src = "const x = 42; console.log(x);"
        calls = extract_api_calls(src)
        assert calls == []

    def test_deduplication(self):
        src = """
        await fetch('/api/users');
        await fetch('/api/users');
        """
        calls = extract_api_calls(src)
        endpoints = [c.endpoint for c in calls]
        assert endpoints.count("/api/users") == 1

    def test_multiple_clients(self):
        src = """
        await fetch('/api/a');
        await axios.get('/api/b');
        """
        calls = extract_api_calls(src)
        assert len(calls) == 2
        client_types = {c.client_type for c in calls}
        assert "fetch" in client_types
        assert "axios" in client_types
