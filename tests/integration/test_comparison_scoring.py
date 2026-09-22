"""比较式评分端到端：plan 声明比较维度 → /compare → 派生标量 → 总分 → 幂等。"""
import json

from fastapi.testclient import TestClient

from octagon_evals.api import create_app
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig


class _Response:
    status = 200
    def __init__(self, content): self.content = content
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()


class ScriptedJudge:
    """按 evidence['x'] 值裁决：compare 取大者胜（相等 tie），rank 降序排列。"""

    def __init__(self):
        self.compare_calls = 0
        self.rank_calls = 0

    def __call__(self, request):
        payload = json.loads(request.data)
        system = payload["messages"][0]["content"]
        user = json.loads(payload["messages"][1]["content"])
        if "pairwise" in system:
            self.compare_calls += 1
            c0, c1 = user["candidates"]
            winner = "tie" if c0["evidence"].get("x") == c1["evidence"].get("x") \
                else (c0["id"] if c0["evidence"]["x"] > c1["evidence"]["x"] else c1["id"])
            content = json.dumps({"winner": winner, "reason": "scripted", "raw": {}})
        else:
            self.rank_calls += 1
            ranked = sorted(user["candidates"], key=lambda c: -c["evidence"]["x"])
            content = json.dumps({"ranking": [c["id"] for c in ranked], "reason": "scripted", "raw": {}})
        return _Response(content)


def _start(client, experiment_id, method, comparison=None):
    dim = {"id": "quality", "weight": 1, "method": method, "question": "Which is better?"}
    if comparison:
        dim["comparison"] = comparison
    payload = {
        "run_id": "run-1",
        "producer": {"variant_id": "agent-a", "model_id": "model-1"},
        "scenario": {"id": "scene", "version": 1},
        "task": {"id": "task"},
        "artifact": {"snapshot_ref": "snapshot://run-1", "content_hash": "sha256:a"},
        "history": {"trajectory_ref": "trace://run-1"},
        "dimensions": [dim],
    }
    client.post("/experiments/" + experiment_id + "/runs", json=payload)
    payload["run_id"] = "run-2"
    payload["artifact"]["content_hash"] = "sha256:b"
    client.post("/experiments/" + experiment_id + "/runs", json=payload)
    payload["run_id"] = "run-3"
    payload["artifact"]["content_hash"] = "sha256:c"
    client.post("/experiments/" + experiment_id + "/runs", json=payload)


def test_pairwise_scoring_end_to_end(tmp_path):
    judge = ScriptedJudge()
    client = TestClient(create_app(str(tmp_path / "pw.db"), judge=AgentJudge(AgentJudgeConfig(), judge)))
    _start(client, "e1", "pairwise_judge", {"strategy": "round_robin", "conversion": "win_count"})

    resp = client.post("/experiments/e1/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 3}, "run-2": {"x": 2}, "run-3": {"x": 1}},
    })
    assert resp.status_code == 200
    scores = resp.json()["scores"]
    assert scores == {"run-1": {"value": 1.0, "source": "pairwise_judge"},
                      "run-2": {"value": 0.5, "source": "pairwise_judge"},
                      "run-3": {"value": 0.0, "source": "pairwise_judge"}}
    assert judge.compare_calls == 3  # round_robin：3 对，各一次

    totals = client.get("/experiments/e1/score").json()["runs"]
    assert totals["run-1"]["total_score"] == 1.0
    assert totals["run-2"]["total_score"] == 0.5
    assert totals["run-3"]["total_score"] == 0.0

    # 幂等：同进程重复触发，复用派生分数，不重新采样。
    again = client.post("/experiments/e1/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 3}, "run-2": {"x": 2}, "run-3": {"x": 1}},
    })
    assert again.status_code == 200
    assert again.json()["scores"] == scores
    assert judge.compare_calls == 3


def test_pairwise_reuses_persisted_primitives_across_restart(tmp_path):
    path = str(tmp_path / "reuse.db")
    judge = ScriptedJudge()
    judge_for_first = AgentJudge(AgentJudgeConfig(), judge)
    client = TestClient(create_app(path, judge=judge_for_first))
    _start(client, "e2", "pairwise_judge")
    client.post("/experiments/e2/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 1}, "run-2": {"x": 0}, "run-3": {"x": 0}},
    })
    assert judge.compare_calls == 3

    # 重启后：原语已落库，命中复用，不重新采样。
    restarted = TestClient(create_app(path, judge=AgentJudge(AgentJudgeConfig(), judge)))
    resp = restarted.post("/experiments/e2/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 1}, "run-2": {"x": 0}, "run-3": {"x": 0}},
    })
    assert resp.status_code == 200
    assert resp.json()["scores"]["run-1"]["value"] == 1.0
    assert judge.compare_calls == 3  # 没有新增采样


def test_listwise_scoring_end_to_end(tmp_path):
    judge = ScriptedJudge()
    client = TestClient(create_app(str(tmp_path / "lw.db"), judge=AgentJudge(AgentJudgeConfig(), judge)))
    _start(client, "e3", "listwise_judge")

    resp = client.post("/experiments/e3/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 1}, "run-2": {"x": 3}, "run-3": {"x": 2}},
    })
    assert resp.status_code == 200
    scores = resp.json()["scores"]
    assert scores["run-2"]["value"] == 1.0
    assert scores["run-3"]["value"] == 0.5
    assert scores["run-1"]["value"] == 0.0
    assert judge.rank_calls == 1  # 一次 rank 调用

    totals = client.get("/experiments/e3/score").json()["runs"]
    assert totals["run-2"]["total_score"] == 1.0
    assert totals["run-1"]["total_score"] == 0.0


def test_compare_rejects_unknown_or_non_comparison_dimension(tmp_path):
    client = TestClient(create_app(str(tmp_path / "bad.db"), judge=AgentJudge(AgentJudgeConfig(), ScriptedJudge())))
    _start(client, "e4", "pairwise_judge")
    # 未知维度
    resp = client.post("/experiments/e4/compare", json={
        "dimension_id": "nope",
        "evidence": {"run-1": {"x": 1}, "run-2": {"x": 0}},
    })
    assert resp.status_code == 422
    # 空证据
    resp = client.post("/experiments/e4/compare", json={"dimension_id": "quality", "evidence": {}})
    assert resp.status_code == 422


def test_comparison_dimensions_do_not_create_per_run_tasks(tmp_path):
    client = TestClient(create_app(str(tmp_path / "notasks.db"), judge=AgentJudge(AgentJudgeConfig(), ScriptedJudge())))
    _start(client, "e5", "pairwise_judge")
    detail = client.get("/experiments/e5").json()
    # comparison 维度不创建 per-run DimensionTask
    for run in detail["runs"]:
        assert run["dimensions"] == []


class _ServiceResponse:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.payload).encode()


class AgenticScriptedOpener:
    """模拟 pi judge 服务：记录请求，按 evidence x 值裁决 compare。"""

    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout=None):
        body = json.loads(request.data)
        self.requests.append(body)
        evidence = body["evidence"]
        rid_a, rid_b = sorted(evidence)
        winner = "tie" if evidence[rid_a].get("x") == evidence[rid_b].get("x") \
            else (rid_a if evidence[rid_a]["x"] > evidence[rid_b]["x"] else rid_b)
        result = {"winner": winner, "reason": "service", "raw": {}}
        return _ServiceResponse({
            "task_id": body["task_id"], "result": result,
            "value": None, "reason": None, "raw": None,
            "source": "agent_judge_agentic",
            "lineage": {"provider": "pi-default", "model": "pi-default", "prompt_version": "agentic-1"},
        })


def test_pairwise_agentic_end_to_end(tmp_path):
    from octagon_evals.scorers.agent_judge_client import AgentJudgeClient, AgentJudgeClientConfig
    opener = AgenticScriptedOpener()
    client = TestClient(create_app(str(tmp_path / "agentic.db"), agentic_judge=AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener)))
    _start(client, "e6", "pairwise_judge_agentic", {"strategy": "round_robin", "conversion": "win_count"})

    resp = client.post("/experiments/e6/compare", json={
        "dimension_id": "quality",
        "evidence": {"run-1": {"x": 2}, "run-2": {"x": 1}, "run-3": {"x": 0}},
    })
    assert resp.status_code == 200
    assert resp.json()["scores"]["run-1"]["source"] == "pairwise_judge_agentic"
    assert resp.json()["scores"] == {
        "run-1": {"value": 1.0, "source": "pairwise_judge_agentic"},
        "run-2": {"value": 0.5, "source": "pairwise_judge_agentic"},
        "run-3": {"value": 0.0, "source": "pairwise_judge_agentic"},
    }
    assert len(opener.requests) == 3
    # 每个请求都带方法级 system_prompt、显式 files 布局、winner schema。
    for body in opener.requests:
        assert "pairwise" in body["system_prompt"]
        assert body["output_schema"]["required"] == ["winner", "reason", "raw"]
        assert any(k.startswith("run-") for k in body["files"])
