"""JEV 集成：`jev_judge` 维度与现有 `agent_judge` 在同一 plan 共存。

关键断言：新增方法后 `agent_judge` 路径行为不变（值/source），`jev_judge`
正常落分——证明纯增量、零破坏。
"""
import json

import pytest
from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig
from octagon_evals.scorers.jev import JevJudge, SystemOneConfig


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


class _FakeJevClient:
    def __init__(self, answers): self.answers = answers; self.state = None
    def judge(self, *, state, questions):
        self.state = state
        return self.answers


def _payload():
    return {
        "run_id": "run-1",
        "producer": {"variant_id": "agent-a", "model_id": "model-1"},
        "scenario": {"id": "scene", "version": 1},
        "task": {"id": "task"},
        "artifact": {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:artifact"},
        "history": {"trajectory_ref": "trace://run-1"},
        "dimensions": [
            {"id": "quality", "weight": 1, "method": "agent_judge", "question": "Is it good?"},
            {
                "id": "jev_quality", "weight": 1, "method": "jev_judge",
                "question": "评估答案质量", "evidence": ["final_answer"],
                "jev_questions": {
                    "correctness": {"type": "score", "instructions": "答案是否正确？",
                                    "criteria": {"low": "错", "high": "对"}},
                    "computed": {"type": "choice", "instructions": "是否计算？",
                                 "criteria": {"yes": "有", "no": "无"}, "expected": "yes"},
                },
            },
        ],
    }


def test_jev_and_agent_judge_coexist_in_one_plan(tmp_path):
    agent = AgentJudge(AgentJudgeConfig(), lambda request: _Response({"value": 0.8, "reason": "supported"}))
    jev = JevJudge(
        config=SystemOneConfig(url="http://x:8100", model="m"),
        client=_FakeJevClient({
            "correctness": {"type": "score", "score": 0.7, "confidence": 0.9},
            "computed": {"type": "choice", "choice": "yes", "confidence": 0.6},
        }),
    )
    client = TestClient(create_app(str(tmp_path / "jev.db"), judge=agent, jev_judge=jev))

    started = client.post("/experiments/e1/runs", json=_payload())
    assert started.status_code == 201
    task_ids = started.json()["task_ids"]
    assert len(task_ids) == 2

    # agent_judge 维度：行为与新增前一致
    s1 = client.post(f"/tasks/{task_ids[0]}/score", json={"evidence": {"artifact": "present"}})
    assert s1.status_code == 200
    assert s1.json()["source"] == "agent_judge" and s1.json()["value"] == 0.8

    # jev_judge 维度：混合均值 (0.7 + 1.0) / 2 = 0.85
    s2 = client.post(f"/tasks/{task_ids[1]}/score", json={"evidence": {"final_answer": "the answer is 4"}})
    assert s2.status_code == 200
    body = s2.json()
    assert body["source"] == "jev_judge" and body["value"] == 0.85

    # 聚合：两维度都已落分，total = (0.8 + 0.85) / 2 = 0.825
    totals = client.get("/experiments/e1/score").json()
    run_total = totals["runs"]["run-1"]
    assert run_total["status"] == "final"
    assert run_total["total_score"] == pytest.approx(0.825)
