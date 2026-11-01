"""Test isolation: the engine's background loop must not outlive the test that started it."""
import pytest

from workday import engine


@pytest.fixture(autouse=True)
def _stop_engine_loop():
    yield
    engine.shutdown()
