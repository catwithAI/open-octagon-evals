"""POST /evaluate —— LLM-as-judge 原子式评分入口的集成测试。

核心不变式：单次请求评完一个 run 的全部维度，复用 service 的评分语义
（deterministic registry / agent judge / jev judge），不建 experiment、不落 task
持久化；结果带每维 lineage 与累计 usage；human / comparison 维度拒绝；judge_config
只覆盖非敏感字段且不碰 API key。
"""
import json
import pytest
from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return json.dumps(self.payload).encode()


class JudgeOpener:
    """记录请求，按 question 返回裁决，带 usage。"""
    def __init__(self, by_question, usage=None):
        self.by_question = by_question
        self.usage = usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        self.requests = []

    def __call__(self, request, *, timeout=None):
        body = json.loads(request.data)
        self.requests.append(body)
        user = json.loads(body["messages"][1]["content"])
        question = user["question"]
        verdict = self.by_question(question) if callable(self.by_question) else self.by_question
        return Response({
            "choices": [{"message": {"content": json.dumps(verdict)}}],
            "usage": self.usage,
        })


def _dimensions():
    return [
        {"id": "task_completion", "weight": 0.5, "method": "deterministic"},
        {"id": "quality", "version": 1, "weight": 0.5, "method": "agent_judge",
         "question": "Is the output quality good?"},
    ]


def _payload(**over):
    payload = {
        "evaluation_id": "ev-1",
        "run_id": "r1",
        "scenario": {"id": "s", "version": 1},
        "task": {"id": "t1"},
        "artifact": {"snapshot_ref": "a", "content_hash": "h"},
        "history": {"trajectory_ref": "tr"},
        "evidence": {"checks": [True, True, False], "candidate_output": "some output"},
        "dimensions": _dimensions(),
    }
    payload.update(over)
    return payload


def _client():
    judge = AgentJudge(
        AgentJudgeConfig(endpoint="http://fake.invalid"),
        JudgeOpener(lambda q: {"value": 0.9, "reason": "solid", "raw": {}}),
    )
    return TestClient(create_app(None, judge=judge))


def test_evaluate_mixed_deterministic_and_agent_judge():
    client = _client()
    resp = client.post("/evaluate", json=_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["evaluation_id"] == "ev-1" and body["run_id"] == "r1"
    by_id = {r["dimension_id"]: r for r in body["results"]}
    # deterministic 维度走 default_registry：2/3 检查通过
    assert by_id["task_completion"]["method"] == "deterministic"
    assert by_id["task_completion"]["value"] == pytest.approx(2 / 3)
    # agent_judge 维度带 lineage
    assert by_id["quality"]["value"] == 0.9
    assert by_id["quality"]["lineage"]["model"] == "stealth/ox-alpha"
    assert "prompt_version" in by_id["quality"]["lineage"]
    # usage 从 judge 实例回传
    assert body["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert body["error"] is None


def test_evaluate_single_agent_judge_dimension_reaches_judge_once():
    opener = JudgeOpener(lambda q: {"value": 0.5, "reason": "meh", "raw": {}})
    judge = AgentJudge(AgentJudgeConfig(endpoint="http://fake.invalid"), opener)
    client = TestClient(create_app(None, judge=judge))
    resp = client.post("/evaluate", json=_payload(dimensions=[
        {"id": "quality", "method": "agent_judge", "question": "Is it good?"},
    ]))
    assert resp.status_code == 200
    assert resp.json()["results"][0]["value"] == 0.5
    assert len(opener.requests) == 1


def test_evaluate_rejects_human_and_comparison_dimensions():
    client = _client()
    for method in ("human_required", "pairwise_judge"):
        resp = client.post("/evaluate", json=_payload(
            evaluation_id=f"ev-{method}",
            dimensions=[{"id": "d", "method": method, "question": "q"}],
        ))
        assert resp.status_code == 409, (method, resp.text)
        assert "流程式" in resp.json()["detail"]


def test_evaluate_rejects_invalid_judge_output():
    judge = AgentJudge(
        AgentJudgeConfig(endpoint="http://fake.invalid"),
        JudgeOpener(lambda q: "I cannot score this."),
    )
    client = TestClient(create_app(None, judge=judge))
    resp = client.post("/evaluate", json=_payload(dimensions=[
        {"id": "quality", "method": "agent_judge", "question": "q"},
    ]))
    assert resp.status_code == 422


def test_evaluate_judge_config_overrides_non_sensitive_fields_only():
    opener = JudgeOpener(lambda q: {"value": 0.6, "reason": "ok", "raw": {}})
    judge = AgentJudge(AgentJudgeConfig(endpoint="http://fake.invalid"), opener)
    client = TestClient(create_app(None, judge=judge))
    resp = client.post("/evaluate", json=_payload(
        evaluation_id="ev-override",
        judge_config={"model": "custom-model", "endpoint": "http://fake.invalid"},
    ))
    assert resp.status_code == 200, resp.text
    # 请求里的 model 被覆盖；key 不过 HTTP（authorization 头不存在）
    assert opener.requests[-1]["model"] == "custom-model"
    assert "authorization" not in {k.lower() for k in opener.requests[-1]}


def test_evaluate_does_not_touch_existing_flow_api():
    """/evaluate 是旁路：不污染 experiment 生命周期，流程式 API 照常可用。"""
    client = _client()
    assert client.post("/evaluate", json=_payload()).status_code == 200
    flow = client.post("/experiments/e1/runs", json={
        "run_id": "r1",
        "scenario": {"id": "s", "version": 1},
        "task": {"id": "t"},
        "artifact": {"snapshot_ref": "a", "content_hash": "h"},
        "history": {"trajectory_ref": "tr"},
        "dimensions": [{"id": "task_completion", "weight": 1, "method": "deterministic"}],
    })
    assert flow.status_code == 201
    task_id = flow.json()["task_ids"][0]
    score = client.post(f"/tasks/{task_id}/score", json={"evidence": {"checks": [True]}})
    assert score.json()["value"] == 1.0


def test_evaluate_usage_is_null_when_judge_reports_none():
    opener = JudgeOpener(
        lambda q: {"value": 0.8, "reason": "ok", "raw": {}},
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    judge = AgentJudge(AgentJudgeConfig(endpoint="http://fake.invalid"), opener)
    client = TestClient(create_app(None, judge=judge))
    resp = client.post("/evaluate", json=_payload(dimensions=[
        {"id": "quality", "method": "agent_judge", "question": "q"},
    ]))
    assert resp.status_code == 200
    assert resp.json()["usage"] is None
