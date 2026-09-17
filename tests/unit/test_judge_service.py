import json

from fastapi.testclient import TestClient

from octagon_evals.judge_service.app import create_judge_app
from octagon_evals.judge_service.config import JudgeServiceConfig
from octagon_evals.judge_service.pi_runner import PiRunner


class _FakeCompletedProcess:
    def __init__(self, stdout, stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _ndjson(text):
    return "\n".join([
        json.dumps({"type": "agent_start"}),
        json.dumps({"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "toolResults": []}}),
        json.dumps({"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": text}]}]}),
        json.dumps({"type": "agent_settled"}),
    ])


def _fake_runner_factory(text):
    return lambda cmd, **kwargs: _FakeCompletedProcess(_ndjson(text))


def _make_app(text, **config_overrides):
    config = JudgeServiceConfig(**config_overrides)
    runner = PiRunner(config, runner=_fake_runner_factory(text))
    return create_judge_app(config, runner=runner)


def test_judge_endpoint_returns_structured_score():
    verdict = json.dumps({"value": 0.75, "reason": "mostly there", "raw": {"passed": ["a"]}})
    client = TestClient(_make_app(verdict))
    resp = client.post("/judge", json={
        "task_id": "t1",
        "dimension_question": "Is it good?",
        "anchors": [],
        "output_schema": {},
        "evidence": {"output": "hello"},
        "lineage": {},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 0.75
    assert body["reason"] == "mostly there"
    assert body["source"] == "agent_judge_agentic"
    assert body["lineage"]["prompt_version"] == "agentic-1"
    assert "pi_version" in body["lineage"]


def test_judge_endpoint_accepts_fenced_json():
    verdict = '```json\n{"value": 0.5, "reason": "fenced", "raw": {}}\n```'
    client = TestClient(_make_app(verdict))
    resp = client.post("/judge", json={"task_id": "t2", "dimension_question": "q", "evidence": {}})
    assert resp.status_code == 200
    assert resp.json()["value"] == 0.5


def test_judge_endpoint_rejects_unparseable_output():
    client = TestClient(_make_app("I cannot score this."))
    resp = client.post("/judge", json={"task_id": "t3", "dimension_question": "q", "evidence": {}})
    assert resp.status_code == 422


def test_judge_endpoint_rejects_duplicate_task():
    verdict = json.dumps({"value": 0.5, "reason": "ok", "raw": {}})
    client = TestClient(_make_app(verdict))
    payload = {"task_id": "dup", "dimension_question": "q", "evidence": {}}
    assert client.post("/judge", json=payload).status_code == 200
    assert client.post("/judge", json=payload).status_code == 409


def test_judge_endpoint_cleans_up_workspace(tmp_path):
    verdict = json.dumps({"value": 0.5, "reason": "ok", "raw": {}})
    client = TestClient(_make_app(verdict, workspace_base=str(tmp_path)))
    resp = client.post("/judge", json={"task_id": "t4", "dimension_question": "q", "evidence": {"a": 1}})
    assert resp.status_code == 200
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("octagon-judge-")]
    assert leftovers == []


def test_judge_health_reports_pi_version():
    client = TestClient(_make_app("x"))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
