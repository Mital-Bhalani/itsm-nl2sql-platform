"""API end to end on a temp database, with the language model replaced by a fake."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import llm


@pytest.fixture
def client(api_app):
    return TestClient(api_app.app)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["datasets"]["default"]["catalog"] is True
    assert body["datasets"]["large"]["exists"] is False


def test_kpis_match_the_seed_facts(client):
    h = client.get("/api/kpis").json()["headline"]
    assert (h["incidents"], h["open"], h["resolved_or_closed"], h["sla_breaches"]) == (500, 50, 440, 66)
    assert (h["sla_breach_rate_pct"], h["reopen_rate_pct"], h["mttr_minutes"]) == (15.0, 8.8, 2828.8)


def test_kpis_last_month_by_team(client):
    teams = client.get("/api/kpis", params={"date_from": "2026-08-01", "date_to": "2026-08-31"}).json()["by_team"]
    breaches = {t["team"]: t["sla_breaches"] for t in teams}
    assert breaches == {"Service Desk": 4, "Network": 3, "Database": 2, "Application Support": 1,
                        "Infrastructure": 0}
    assert max(teams, key=lambda t: t["sla_breach_rate_pct"])["team"] == "Database"


def test_kpis_reject_bad_date(client):
    assert client.get("/api/kpis", params={"date_from": "Aug 1"}).status_code == 422


def test_explorer_paging_filters_and_masking(client):
    page = client.get("/api/tables/incidents", params={"f_priority": 1, "size": 5, "page": 2}).json()
    assert page["total"] == 17 and page["pages"] == 4 and len(page["rows"]) == 5
    assert all(r["priority"] == 1 for r in page["rows"]) and "assignment_group" in page["rows"][0]
    users = client.get("/api/tables/users", params={"size": 200}).json()
    assert users["total"] == 40 and {r["name"] for r in users["rows"]} == {"***"}


@pytest.mark.parametrize("path, params", [
    ("/api/tables/sqlite_master", {}),
    ("/api/tables/incidents", {"f_nope": "1"}),
    ("/api/tables/incidents", {"sort": "id; DROP TABLE incidents"}),
    ("/api/tables/users", {"sort": "name"}),
    ("/api/tables/users", {"f_name": "x"}),
    ("/api/catalog/secrets", {}),
    ("/api/overview", {"dataset": "other"}),
])
def test_explorer_rejects_unknown_or_personal(client, path, params):
    assert client.get(path, params=params).status_code == 400


def test_incident_detail(client):
    body = client.get("/api/incidents/1").json()
    assert body["assignment_group"] and body["target_minutes"] > 0
    assert client.get("/api/incidents/999999").status_code == 404


def test_catalog_sections(client):
    assert len(client.get("/api/catalog/metrics").json()) == 3
    assert any(g["term"] == "SLA breach" for g in client.get("/api/catalog/glossary").json())


def test_ask_answers_with_sql_and_audit(client, api_app, fake_model):
    replies, calls = fake_model
    replies += ["```sql\nSELECT COUNT(i.id) AS open_p1 FROM incidents i "
                "WHERE i.status IN ('New', 'In Progress', 'On Hold') AND i.priority = 1\n```",
                "There is 1 open P1 incident."]
    body = client.post("/api/ask", json={"question": "How many P1 incidents are open?"}).json()
    assert body["rows"] == [[1]] and body["answer"] == "There is 1 open P1 incident."
    assert body["sql"].endswith("LIMIT 1000") and body["error"] is None and len(calls) == 2
    last = json.loads(api_app.settings.audit_log.read_text(encoding="utf-8").splitlines()[-1])
    assert last["status"] == "answered" and last["request_id"] == body["request_id"]


def test_ask_refuses_without_calling_the_model(client, fake_model):
    _, calls = fake_model
    body = client.post("/api/ask", json={"question": "Who is the assignee of most P1 tickets?"}).json()
    assert body["refusal"] and body["sql"] is None and calls == []


def test_ask_blocks_unsafe_sql(client, fake_model):
    replies, _ = fake_model
    replies.append("```sql\nDELETE FROM incidents\n```")
    body = client.post("/api/ask", json={"question": "Remove all incidents please"}).json()
    assert body["unsafe"] == "not a SELECT statement" and body["rows"] == []


def test_ask_blocks_personal_data(client, fake_model):
    replies, _ = fake_model
    replies.append("```sql\nSELECT * FROM users\n```")
    body = client.post("/api/ask", json={"question": "List every team member"}).json()
    assert "personal data" in body["error"] and body["rows"] == []


def test_ask_repairs_sql_once(client, fake_model):
    replies, calls = fake_model
    replies += ["```sql\nSELECT COUNT(*) FROM incident\n```",
                "```sql\nSELECT COUNT(*) AS n FROM incidents\n```", "There are 500 incidents."]
    body = client.post("/api/ask", json={"question": "How many incidents are there?"}).json()
    assert body["repaired"] is True and body["rows"] == [[500]]
    assert "no such table: incident" in calls[1]["user"]


def test_ask_answer_falls_back_when_summary_fails(client, fake_model):
    replies, _ = fake_model
    replies += ["```sql\nSELECT COUNT(*) AS n FROM incidents\n```", llm.AgentAPIError("down")]
    body = client.post("/api/ask", json={"question": "How many incidents are there?"}).json()
    assert body["answer"] == "The answer is 500."


def test_ask_model_down_is_503(client, fake_model):
    replies, _ = fake_model
    replies.append(llm.AgentAPIError("no credits"))
    response = client.post("/api/ask", json={"question": "How many incidents are there?"})
    assert response.status_code == 503 and "no credits" in response.json()["detail"]


def test_ask_validates_input(client):
    assert client.post("/api/ask", json={"question": "x"}).status_code == 422
    assert client.post("/api/ask", json={"question": "How many?", "provider": "nope"}).status_code == 400


def test_api_key_required_when_configured(client, api_app, monkeypatch):
    monkeypatch.setattr(api_app.settings, "api_key", "secret")
    assert client.get("/api/groups").status_code == 401
    assert client.get("/api/groups", headers={"X-API-Key": "secret"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_rate_limit(client, api_app, monkeypatch, fake_model):
    monkeypatch.setattr(api_app.settings, "rate_limit_per_min", 2)
    api_app._calls.clear()
    codes = [client.post("/api/ask", json={"question": "Who is the assignee?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    api_app._calls.clear()


def test_self_test_eval_job(client):
    job = client.post("/api/evals", json={"mode": "self-test"}).json()
    for _ in range(100):
        job = client.get(f"/api/evals/{job['id']}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "done" and job["passed"] == job["total"] == 15


def test_live_eval_needs_a_configured_provider(client, monkeypatch):
    monkeypatch.setattr(llm, "available_providers", lambda: [
        {"name": "openai", "configured": False}, {"name": "anthropic", "configured": False}])
    response = client.post("/api/evals", json={"mode": "live", "provider": "anthropic"})
    assert response.status_code == 400


def test_reconcile_all_checks_match(client):
    body = client.get("/api/reconcile").json()
    assert body["total"] >= 20 and body["passed"] == body["total"]


def test_sql_console_is_read_only_and_guarded(client):
    body = client.post("/api/sql", json={"sql": "SELECT priority, COUNT(*) FROM incidents GROUP BY priority"}).json()
    assert body["rows"] == [[1, 17], [2, 63], [3, 275], [4, 145]] and body["sql"].endswith("LIMIT 1000")
    for bad in ("DELETE FROM incidents", "SELECT * FROM users", "SELECT * FROM nope"):
        assert client.post("/api/sql", json={"sql": bad}).status_code == 400


def test_changes_in_the_database_show_up_without_restart(client, db_path):
    import sqlite3
    before = client.get("/api/kpis").json()["headline"]["open"]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO incidents (id, short_desc, priority, status, assignment_group_id, "
                     "opened_at) VALUES (99999, 'test row', 1, 'New', 1, '2026-09-27 12:00:00')")
        conn.commit()
        assert client.get("/api/kpis").json()["headline"]["open"] == before + 1
        assert client.get("/api/incidents/99999").json()["short_desc"] == "test row"
        assert client.get("/api/reconcile").json()["passed"] == client.get("/api/reconcile").json()["total"]
    finally:
        conn.execute("DELETE FROM incidents WHERE id = 99999")
        conn.commit()
        conn.close()
    assert client.get("/api/kpis").json()["headline"]["open"] == before


def test_ask_returns_followups(client, fake_model):
    replies, _ = fake_model
    replies += ["```sql\nSELECT COUNT(*) AS n FROM incidents\n```",
                '{"answer": "There are 500 incidents.", "followups": ["How many are open?", '
                '"Which team has the most?", "What is the MTTR?"]}']
    body = client.post("/api/ask", json={"question": "How many incidents are there?"}).json()
    assert body["answer"] == "There are 500 incidents." and len(body["followups"]) == 3


def test_incident_timeline_and_similar(client):
    body = client.get("/api/incidents/2").json()
    assert [e["event"] for e in body["timeline"]][0] == "Opened"
    assert body["sla_due_at"] and body["target_used_pct"] is not None
    similar = client.get("/api/incidents/2/similar").json()
    assert 0 < len(similar) <= 5 and all(s["id"] != 2 for s in similar)
    assert similar == sorted(similar, key=lambda s: -s["similarity"])
    assert client.get("/api/incidents/999999/similar").status_code == 404


def test_feedback_is_audited(client, api_app):
    response = client.post("/api/feedback", json={"request_id": "abc123", "rating": "down",
                                                  "question": "How many?"})
    assert response.status_code == 201
    last = json.loads(api_app.settings.audit_log.read_text(encoding="utf-8").splitlines()[-1])
    assert last["kind"] == "feedback" and last["rating"] == "down"
    assert client.post("/api/feedback", json={"request_id": "abc123", "rating": "meh"}).status_code == 422


def test_connection_works_across_threads(db_path):
    # FastAPI opens the connection in the dependency and may run the endpoint on another
    # worker thread (seen live as HTTP 500s when the React UI sent requests in parallel).
    from concurrent.futures import ThreadPoolExecutor
    from api import services
    conn = services.connect(db_path)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda: services.groups(conn)).result()[0]["name"]
    finally:
        conn.close()
