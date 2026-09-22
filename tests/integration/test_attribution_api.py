"""归因 API：单任务 / run 批量归因；缺分数 422；与现有评分共存。"""
import json

from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.attribution.service import AttributionService
from octagon_evals.judge_service.config import JudgeServiceConfig
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


class _FakeProc:
    def __init__(self, text):
        self.returncode = 0
        self.stdout = text
        self.stderr = ""


def _ndjson(text):
    events = [{"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": text}]}]}]
    return "\n".join(json.dumps(e) for e in events)


def _attribution_json():
    return {
        "schema_version": "octagon_evals.attribution.v1", "status": "candidate",
        "phenomenon": "agent 未完成核对，得分 0.2",
        "root_causes": [{"category": "agent_behavior", "description": "没有读取证据就作答", "confidence": "high"}],
        "suggestions": [{"target": "agent", "action": "先读 evidence 再作答", "rationale": "核对能避免臆断"}],
        "notes": [],
    }


def _make_attributor():
    payload = json.dumps(_attribution_json(), ensure_ascii=False)
    def fake_runner(config):
        from octagon_evals.judge_service.pi_runner import PiRunner
        return PiRunner(config, runner=lambda cmd, **kw: _FakeProc(_ndjson(payload)))
    return AttributionService(config=JudgeServiceConfig(pi_bin="pi"), runner_factory=fake_runner)


def _payload():
    return {
        "run_id": "run-1",
        "producer": {"variant_id": "agent-a", "model_id": "model-1"},
        "scenario": {"id": "scene", "version": 1},
        "task": {"id": "task"},
        "artifact": {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:artifact"},
        "history": {"trajectory_ref": "trace://run-1"},
        "dimensions": [
            {"id": "quality", "weight": 1, "method": "agent_judge", "question": "Is it good?",
             "anchors": [{"score": 0.0, "label": "bad", "description": "没核对"}]},
            {"id": "task_completion", "weight": 1, "method": "deterministic"},
        ],
    }


def _start_and_score(client):
    started = client.post("/experiments/e1/runs", json=_payload())
    task_ids = started.json()["task_ids"]
    # score agent_judge dim
    s1 = client.post(f"/tasks/{task_ids[0]}/score", json={"evidence": {"final_answer": "385"}})
    # score deterministic dim
    s2 = client.post(f"/tasks/{task_ids[1]}/score", json={"evidence": {"checks": [True, False]}})
    return task_ids, s1, s2


def test_attribute_single_task(tmp_path):
    agent = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.2, "reason": "missing check"}))
    client = TestClient(create_app(str(tmp_path / "attr.db"), judge=agent, attribution=_make_attributor()))
    task_ids, s1, _ = _start_and_score(client)
    assert s1.status_code == 200

    resp = client.post(f"/tasks/{task_ids[0]}/attribute", json={"evidence": {"final_answer": "385", "history": {"t": 1}}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "candidate"
    assert body["phenomenon"] == "agent 未完成核对，得分 0.2"
    assert body["root_causes"][0]["category"] == "agent_behavior"
    assert body["lineage"]["prompt_version"] == "attribution-v1"


def test_attribute_run_batch(tmp_path):
    agent = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.2, "reason": "missing check"}))
    client = TestClient(create_app(str(tmp_path / "attr.db"), judge=agent, attribution=_make_attributor()))
    _start_and_score(client)

    resp = client.post("/runs/run-1/attribute", json={"evidence": {"final_answer": "385"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-1"
    assert len(body["attributions"]) == 2  # 两个已评分维度
    assert {a["dimension_id"] for a in body["attributions"]} == {"quality", "task_completion"}
    assert all(a["attribution"]["status"] == "candidate" for a in body["attributions"])


def test_attribute_unscored_task_422(tmp_path):
    agent = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.2, "reason": "missing check"}))
    client = TestClient(create_app(str(tmp_path / "attr.db"), judge=agent, attribution=_make_attributor()))
    started = client.post("/experiments/e1/runs", json=_payload())
    task_ids = started.json()["task_ids"]
    # 只评 deterministic，不评 agent_judge
    client.post(f"/tasks/{task_ids[1]}/score", json={"evidence": {"checks": [True]}})

    resp = client.post(f"/tasks/{task_ids[0]}/attribute", json={"evidence": {"x": 1}})
    assert resp.status_code == 422
    assert "no resolved score" in resp.json()["detail"]


def test_attribute_agent_judge_scoring_unaffected(tmp_path):
    # 归因模块存在时，agent_judge 评分照常
    agent = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.8, "reason": "ok"}))
    client = TestClient(create_app(str(tmp_path / "attr.db"), judge=agent, attribution=_make_attributor()))
    task_ids, s1, _ = _start_and_score(client)
    assert s1.status_code == 200 and s1.json()["source"] == "agent_judge" and s1.json()["value"] == 0.8
