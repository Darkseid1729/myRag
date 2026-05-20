"""Tests for intent router."""

from src.intent.intent_router import IntentRouter, Intent

router = IntentRouter()


def test_symbol_lookup():
    d = router.route("where is the useAuth hook defined?")
    assert d.intent == Intent.SYMBOL_LOOKUP


def test_architecture():
    d = router.route("explain how authentication works in this project")
    assert d.intent == Intent.ARCHITECTURE


def test_route_tracing():
    d = router.route("which files affect /dashboard route")
    assert d.intent == Intent.ROUTE_TRACING


def test_impact_analysis():
    d = router.route("what breaks if I change useAuth")
    assert d.intent == Intent.IMPACT_ANALYSIS


def test_debugging():
    d = router.route("why is the login broken")
    assert d.intent == Intent.DEBUGGING


def test_default_fallback():
    d = router.route("something completely generic")
    assert d.intent is not None  # must return some intent
