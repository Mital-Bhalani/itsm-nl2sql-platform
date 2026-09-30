"""
Shared fixtures. A fresh database is built outside the repo (pytest's temp folder) with
db/seed.py and semantics/build_catalog.py, so tests never touch db/tickets.sqlite and never
call a real language model.

    python -B -m pytest tests -p no:cacheprovider
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
for folder in ("", "agent", "semantics", "evals", "db"):
    path = str(ROOT / folder) if folder else str(ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "tickets.sqlite"
    for script, flag in (("db/seed.py", "--out"), ("semantics/build_catalog.py", "--db")):
        subprocess.run([sys.executable, "-B", str(ROOT / script), flag, str(path)],
                       check=True, capture_output=True, cwd=ROOT)
    return path


@pytest.fixture(scope="session")
def api_app(db_path, tmp_path_factory):
    """The FastAPI app pointed at the temp database, with no API key and a temp audit log."""
    os.environ.update(DB_PATH=str(db_path), DB_LARGE_PATH=str(db_path.parent / "absent.sqlite"),
                      AUDIT_LOG=str(tmp_path_factory.mktemp("logs") / "audit.jsonl"),
                      STATE_DB=str(tmp_path_factory.mktemp("state") / "state.sqlite"),
                      RATE_LIMIT_PER_MIN="1000")
    os.environ.pop("APP_API_KEY", None)
    from api import main
    return main


@pytest.fixture
def fake_model(monkeypatch):
    """Replace the language model: each call returns the next queued reply (or a default)."""
    import llm
    import nl2sql

    replies, calls = [], []

    def complete(system, user, provider=None, model=None):
        calls.append({"system": system, "user": user, "provider": provider, "model": model})
        text = replies.pop(0) if replies else "The answer is in the table."
        if isinstance(text, Exception):
            raise text
        return llm.LLMReply(text=text, provider=provider or "openai", model=model or "fake-model",
                            latency_ms=1, tokens_in=10, tokens_out=5)

    monkeypatch.setattr(nl2sql, "complete", complete)
    return replies, calls
