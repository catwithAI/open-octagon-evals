import json

from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": json.dumps(self.payload)}}]}).encode()


def _payload(method="deterministic"):
    return {
        "run_id": "run-1",
        "producer": {"variant_id": "agent-a", "model_id": "model-1"},
        "scenario": {"id": "scene", "version": 1},
        "task": {"id": "task"},
        "artifact": {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:artifact"},
        "history": {"trajectory_ref": "trace://run-1"},
        "dimensions": [{"id": "quality" if method == "agent_judge" else "task_completion", "weight": 1, "method": method, "question": "Is it good?"}],
    }


def test_agent_judge_completes_single_scoring_loop(tmp_path):
    judge = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.8, "reason": "supported"}))
    client = TestClient(create_app(str(tmp_path / "judge.db"), judge=judge))
    started = client.post("/experiments/e1/runs", json=_payload("agent_judge"))
    assert started.status_code == 201
    task_id = started.json()["task_ids"][0]

    scored = client.post(f"/tasks/{task_id}/score", json={"evidence": {"artifact": "present"}})
    assert scored.status_code == 200
    assert scored.json()["value"] == 0.8
    assert client.get("/experiments/e1/score").json()["runs"]["run-1"]["total_score"] == 0.8


def test_producer_metadata_and_progress_survive_restart(tmp_path):
    path = str(tmp_path / "metadata.db")
    client = TestClient(create_app(path))
    started = client.post("/experiments/e1/runs", json=_payload())
    task_id = started.json()["task_ids"][0]
    listing = client.get("/experiments").json()[0]
    assert listing["status"] == "pending" and listing["resolved_count"] == 0
    client.post(f"/tasks/{task_id}/score", json={"evidence": {"checks": [True]}})

    restarted = TestClient(create_app(path))
    detail = restarted.get("/experiments/e1").json()
    assert detail["runs"][0]["producer"] == {"variant_id": "agent-a", "model_id": "model-1"}
    assert restarted.get("/experiments").json()[0]["status"] == "final"


def test_replaying_run_is_idempotent_but_conflicting_input_is_rejected(tmp_path):
    client = TestClient(create_app(str(tmp_path / "replay.db")))
    assert client.post("/experiments/e1/runs", json=_payload()).status_code == 201
    replay = client.post("/experiments/e1/runs", json=_payload())
    assert replay.status_code == 201 and len(replay.json()["task_ids"]) == 1
    changed = _payload()
    changed["artifact"] = {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:other"}
    assert client.post("/experiments/e1/runs", json=changed).status_code == 422
