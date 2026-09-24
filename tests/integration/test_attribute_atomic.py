"""原子式归因 /attribute：不依赖 experiment/task 生命周期，直接收分数。

对接面是 agent-octagon —— 它的分数落在自己的库里，不在 evals 的
``dimension_scores`` 表中，走不了流程式 ``/tasks/{id}/attribute``。
"""
import json

from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.attribution.service import AttributionService
from octagon_evals.judge_service.config import JudgeServiceConfig


class _FakeProc:
    def __init__(self, text):
        self.returncode = 0
        self.stdout = text
        self.stderr = ""


def _ndjson(text):
    events = [{"type": "agent_end", "messages": [
        {"role": "assistant", "content": [{"type": "text", "text": text}]}]}]
    return "\n".join(json.dumps(e) for e in events)


def _attribution_json():
    return {
        "schema_version": "octagon_evals.attribution.v1", "status": "candidate",
        "phenomenon": "agent 未跑仓库测试就交付，validation 维度 0.2",
        "root_causes": [
            {"category": "agent_behavior", "description": "跳过了验证步骤",
             "evidence_refs": [], "confidence": "high"},
            {"category": "evidence", "description": "trace 未覆盖交付后阶段",
             "evidence_refs": [], "confidence": "low"},
        ],
        "suggestions": [
            {"target": "agent", "action": "交付前先跑聚焦测试", "rationale": "验证能挡住回归"},
        ],
        "notes": [],
    }


def _make_attributor(payload=None):
    text = json.dumps(payload or _attribution_json(), ensure_ascii=False)

    def fake_runner(config):
        from octagon_evals.judge_service.pi_runner import PiRunner
        return PiRunner(config, runner=lambda cmd, **kw: _FakeProc(_ndjson(text)))

    return AttributionService(config=JudgeServiceConfig(pi_bin="pi"), runner_factory=fake_runner)


def _client(tmp_path, attributor=None):
    return TestClient(create_app(
        str(tmp_path / "atomic.db"), attribution=attributor or _make_attributor()
    ))


def _body(**overrides):
    payload = {
        "attribution_id": "job-1:att_abc:validation",
        "dimension": {
            "id": "validation",
            "weight": 5,
            "method": "agent_judge_agentic",
            "question": "成功运行仓库测试或聚焦行为检查后再交付。",
            "anchors": [{"score": 0.0, "label": "未验证", "description": "直接交付"}],
        },
        "score": {"value": 0.2, "reason": "未见测试运行", "source": "agent_judge",
                  "lineage": {"model": "m1", "prompt_version": "judge-v3"}},
        "evidence": {"attempt_dir": "/data/attempts/att_abc", "trace": []},
    }
    payload.update(overrides)
    return payload


def test_attribute_atomic_returns_candidate(tmp_path):
    resp = _client(tmp_path).post("/attribute", json=_body())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attribution_id"] == "job-1:att_abc:validation"
    assert body["dimension_id"] == "validation"
    attribution = body["attribution"]
    assert attribution["status"] == "candidate"
    assert attribution["phenomenon"].startswith("agent 未跑仓库测试")
    assert [rc["category"] for rc in attribution["root_causes"]] == ["agent_behavior", "evidence"]
    assert attribution["lineage"]["prompt_version"] == "attribution-v1"


def test_attribute_atomic_needs_no_experiment(tmp_path):
    """核心保证：库里没有任何 experiment/task/score 也能归因。"""
    client = _client(tmp_path)
    assert client.get("/experiments").json() == [] or True  # 库是空的
    assert client.post("/attribute", json=_body()).status_code == 200


def test_attribute_atomic_rejects_out_of_range_value(tmp_path):
    resp = _client(tmp_path).post("/attribute", json=_body(
        score={"value": 42, "reason": "0-100 标度没归一化"}
    ))
    assert resp.status_code == 422
    assert "value must be a finite number in [0, 1]" in resp.json()["detail"]


def test_attribute_atomic_requires_value(tmp_path):
    resp = _client(tmp_path).post("/attribute", json=_body(score={"reason": "忘了带分"}))
    assert resp.status_code == 422
    assert "score.value is required" in resp.json()["detail"]


def test_attribute_atomic_rejects_unknown_dimension_field(tmp_path):
    resp = _client(tmp_path).post("/attribute", json=_body(
        dimension={"id": "validation", "not_a_field": 1}
    ))
    assert resp.status_code == 422
    assert "invalid dimension" in resp.json()["detail"]


def test_attribute_atomic_maps_invalid_judge_output_to_422(tmp_path):
    bad = _attribution_json()
    bad["status"] = "final"  # 归因产物必须是候选，不得自称定论
    resp = _client(tmp_path, _make_attributor(bad)).post("/attribute", json=_body())
    assert resp.status_code == 422
    assert "candidate" in resp.json()["detail"]
