"""Security regressions: each test is an attack that used to work, or a limit that must hold."""

import pytest
from fastapi.testclient import TestClient

import llm
import nl2sql


@pytest.fixture
def client(api_app):
    return TestClient(api_app.app)


def sql(client, query):
    return client.post("/api/sql", json={"sql": query})


# -----------------------------------------------------------------------------
#  SQL console and generated SQL
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "SELECT * FROM pragma_database_list",          # revealed the server's file path
    "SELECT name FROM pragma_table_list",
    "SELECT * FROM pragma_table_info('users')",
])
def test_pragma_functions_are_blocked(client, query):
    response = sql(client, query)
    assert response.status_code == 400 and "not allowed" in response.json()["detail"]


def test_row_cap_holds_whatever_the_limit(client):
    body = sql(client, "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) "
                       "SELECT x FROM r LIMIT 3000000").json()
    assert body["row_count"] == nl2sql.MAX_ROWS and body["truncated"] is True


@pytest.mark.parametrize("query", ["SELECT length(zeroblob(400000000))",
                                   "SELECT hex(zeroblob(50000000))"])
def test_huge_values_are_refused(client, query):
    response = sql(client, query)
    assert response.status_code == 400 and "larger than" in response.json()["detail"]


def test_extension_loading_is_blocked(client):
    response = sql(client, "SELECT load_extension('evil')")
    assert response.status_code == 400 and "load_extension" in response.json()["detail"]


def test_personal_data_still_blocked_with_clear_reason(client):
    detail = sql(client, "SELECT * FROM users").json()["detail"]
    assert "personal data" in detail


def test_long_query_times_out(client, monkeypatch):
    monkeypatch.setattr(nl2sql, "QUERY_TIMEOUT_MS", 200)
    monkeypatch.setattr(nl2sql.run_sql, "__defaults__", (200,))
    response = sql(client, "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r "
                           "LIMIT 100000000) SELECT count(*) FROM r")
    assert response.status_code == 400 and "timed out" in response.json()["detail"]


def test_generated_sql_gets_the_same_protection(client, fake_model):
    replies, _ = fake_model
    replies.append("```sql\nSELECT * FROM pragma_database_list\n```")
    body = client.post("/api/ask", json={"question": "How many incidents are there?"}).json()
    assert body["rows"] == [] and body["unsafe"] and "not allowed" in body["unsafe"]


# -----------------------------------------------------------------------------
#  API layer
# -----------------------------------------------------------------------------
def test_rate_limit_ignores_changing_api_key_header(client, api_app, monkeypatch):
    monkeypatch.setattr(api_app.settings, "rate_limit_per_min", 2)
    api_app.state.clear_rate_hits()
    codes = [sql(client, "SELECT 1").status_code if n == 0 else
             client.post("/api/sql", json={"sql": "SELECT 1"}, headers={"X-API-Key": f"k{n}"}).status_code
             for n in range(3)]
    api_app.state.clear_rate_hits()
    assert codes == [200, 200, 429]


def test_unlisted_model_is_rejected(client, fake_model):
    response = client.post("/api/ask", json={"question": "How many incidents are there?",
                                             "provider": "openai", "model": "some-expensive-model"})
    assert response.status_code == 400 and "not enabled" in response.json()["detail"]
    ok = client.post("/api/ask", json={"question": "How many incidents are there?",
                                       "provider": "openai", "model": llm.default_model("openai")})
    assert ok.status_code == 200


def test_extra_models_can_be_allowed(monkeypatch):
    monkeypatch.setenv("LLM_ALLOWED_MODELS", "gpt-4o, anthropic:claude-sonnet-5-5")
    assert "gpt-4o" in llm.allowed_models("openai")
    assert "claude-sonnet-5-5" in llm.allowed_models("anthropic")
    assert "claude-sonnet-5-5" not in llm.allowed_models("openai")


def test_api_keys_are_redacted_from_model_errors(client, fake_model):
    replies, _ = fake_model
    replies.append(llm.AgentAPIError("AuthenticationError: Incorrect API key provided: sk-proj-Ab12****WXyz9."))
    response = client.post("/api/ask", json={"question": "How many incidents are there?"})
    assert response.status_code == 503
    assert "sk-proj" not in response.text and "[redacted]" in response.json()["detail"]


def test_non_ascii_api_key_is_401_not_500(client, api_app, monkeypatch):
    monkeypatch.setattr(api_app.settings, "api_key", "secret")
    response = client.get("/api/groups", headers={"X-API-Key": "sécret".encode("utf-8")})
    assert response.status_code == 401


def test_security_headers(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_request_id_is_sanitised(client):
    bad = client.get("/health", headers={"X-Request-ID": "x" * 500})
    assert len(bad.headers["X-Request-ID"]) <= 64
    good = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert good.headers["X-Request-ID"] == "abc-123"


def test_eval_runs_are_capped(client, api_app, monkeypatch):
    monkeypatch.setattr(api_app, "MAX_RUNNING_JOBS", 0)
    response = client.post("/api/evals", json={"mode": "self-test"})
    assert response.status_code == 429
