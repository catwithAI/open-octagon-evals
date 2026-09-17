import json

from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.scorers.agent_judge_client import AgentJudgeClient, AgentJudgeClientConfig


class _FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _judge_response(value, reason, **lineage):
    return {
        "task_id": "stub",
        "value": value,
        "reason": reason,
        "raw": {},
        "source": "agent_judge_agentic",
        "lineage": {
            "provider": "pi-default",
            "model": "pi-default",
            "prompt_version": "agentic-1",
            **lineage,
        },
    }


def _payload():
    return {
        "run_id": "run-1",
        "producer": {"variant_id": "agent-a", "model_id": "model-1"},
        "scenario": {"id": "scene", "version": 1},
        "task": {"id": "task"},
        "artifact": {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:artifact"},
        "history": {"trajectory_ref": "trace://run-1"},
        "dimensions": [{"id": "quality", "weight": 1, "method": "agent_judge_agentic", "question": "Is it good?"}],
    }


def test_agentic_client_timeout_exceeds_judge_timeout():
    assert AgentJudgeClientConfig().timeout > 300


def test_agentic_judge_completes_scoring_loop(tmp_path):
    opener = lambda req, timeout=None: _FakeResponse(_judge_response(0.8, "supported"))
    agentic_judge = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener=opener)
    client = TestClient(create_app(str(tmp_path / "agentic.db"), agentic_judge=agentic_judge))

    started = client.post("/experiments/e1/runs", json=_payload())
    assert started.status_code == 201
    task_id = started.json()["task_ids"][0]

    scored = client.post(f"/tasks/{task_id}/score", json={"evidence": {"artifact": "present"}})
    assert scored.status_code == 200
    assert scored.json()["value"] == 0.8
    assert scored.json()["source"] == "agent_judge_agentic"
    assert client.get("/experiments/e1/score").json()["runs"]["run-1"]["total_score"] == 0.8


def test_agentic_judge_is_single_call_per_dimension(tmp_path):
    opener = lambda req, timeout=None: _FakeResponse(_judge_response(0.8, "ok"))
    agentic_judge = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener=opener)
    client = TestClient(create_app(str(tmp_path / "once.db"), agentic_judge=agentic_judge))
    task_id = client.post("/experiments/e1/runs", json=_payload()).json()["task_ids"][0]

    assert client.post(f"/tasks/{task_id}/score", json={"evidence": {}}).status_code == 200
    # The client refuses a second sample of the same dimension.
    replayed = client.post(f"/tasks/{task_id}/score", json={"evidence": {}})
    assert replayed.status_code == 422
