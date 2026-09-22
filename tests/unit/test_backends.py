"""两个后端（inline / agentic）的 compare / rank 特化：prompt、请求形状、校验、去重。"""
import json
import pytest

from octagon_evals.errors import InvalidJudgeOutput
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig
from octagon_evals.scorers.agent_judge_client import AgentJudgeClient, AgentJudgeClientConfig


class _Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.body).encode()


def _chat_body(content):
    return {"choices": [{"message": {"content": content}}]}


class _CapturingOpener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None
        self.timeout = None
    def __call__(self, request, timeout=None):
        self.request = request
        self.timeout = timeout
        return _Response(self.payload)


# ---------- inline backend ----------

def _inline(payload):
    return AgentJudge(AgentJudgeConfig(), _CapturingOpener(_chat_body(json.dumps(payload))))

CANDIDATES = [{"id": "run-a", "evidence": {"x": 1}}, {"id": "run-b", "evidence": {"x": 0}}]


def test_inline_compare_sends_pairwise_prompt_and_parses_winner():
    opener = _CapturingOpener(_chat_body(json.dumps({"winner": "run-b", "reason": "b wins", "raw": {}})))
    judge = AgentJudge(AgentJudgeConfig(), opener)
    verdict = judge.compare("p1", CANDIDATES, "Which is better?")
    payload = json.loads(opener.request.data)
    assert "pairwise" in payload["messages"][0]["content"]
    user = json.loads(payload["messages"][1]["content"])
    assert user["candidates"][0]["id"] == "run-a"
    assert user["allow_ties"] is True
    assert verdict == {"winner": "run-b", "reason": "b wins", "raw": {}}
    with pytest.raises(RuntimeError):
        judge.compare("p1", CANDIDATES, "again")  # 每 pair 只调用一次


def test_inline_rank_sends_listwise_prompt_and_parses_ranking():
    opener = _CapturingOpener(_chat_body(json.dumps({"ranking": ["run-a", "run-b"], "reason": "order", "raw": {}})))
    judge = AgentJudge(AgentJudgeConfig(), opener)
    verdict = judge.rank("r1", CANDIDATES, "Rank them.")
    payload = json.loads(opener.request.data)
    assert "listwise" in payload["messages"][0]["content"]
    assert verdict["ranking"] == ["run-a", "run-b"]


def test_inline_rank_rejects_non_permutation():
    opener = _CapturingOpener(_chat_body(json.dumps({"ranking": ["run-a"], "raw": {}})))
    judge = AgentJudge(AgentJudgeConfig(), opener)
    with pytest.raises(InvalidJudgeOutput):
        judge.rank("r2", CANDIDATES, "Rank them.")


# ---------- agentic backend ----------

def _agentic(payload):
    return AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), _CapturingOpener(payload))


def _service_response(result):
    return {
        "task_id": "x", "result": result,
        "value": result.get("value"),
        "reason": result.get("reason"), "raw": result.get("raw"),
        "source": "agent_judge_agentic",
        "lineage": {"provider": "pi-default", "model": "pi-default", "prompt_version": "agentic-1"},
    }


def test_agentic_compare_sends_system_prompt_files_and_evidence_map():
    opener = _CapturingOpener(_service_response({"winner": "run-a", "reason": "a wins", "raw": {}}))
    client = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener)
    verdict = client.compare("c1", CANDIDATES, "Which is better?")
    body = json.loads(opener.request.data)
    assert "pairwise" in body["system_prompt"]
    assert body["output_schema"]["required"] == ["winner", "reason", "raw"]
    assert body["evidence"] == {"run-a": {"x": 1}, "run-b": {"x": 0}}
    assert body["files"] == {"run-a/x": 1, "run-b/x": 0}  # 每候选独立文件
    assert verdict == {"winner": "run-a", "reason": "a wins", "raw": {}}
    with pytest.raises(RuntimeError):
        client.compare("c1", CANDIDATES, "again")


def test_agentic_rank_returns_ranking():
    opener = _CapturingOpener(_service_response({"ranking": ["run-b", "run-a"], "reason": "order", "raw": {}}))
    client = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener)
    verdict = client.rank("rk1", CANDIDATES, "Rank them.")
    body = json.loads(opener.request.data)
    assert body["output_schema"]["required"] == ["ranking", "reason", "raw"]
    assert verdict["ranking"] == ["run-b", "run-a"]


def test_agentic_compare_rejects_unknown_winner():
    opener = _CapturingOpener(_service_response({"winner": "run-x", "reason": "?", "raw": {}}))
    client = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), opener)
    with pytest.raises(InvalidJudgeOutput):
        client.compare("c2", CANDIDATES, "Which is better?")


def test_agentic_client_surfaces_judge_service_error_instead_of_crashing():
    import io
    from urllib.error import HTTPError

    def _failing_opener(request, timeout=None):
        raise HTTPError(request.full_url, 422, "Unprocessable Content",
                        {"Content-Type": "application/json"},
                        io.BytesIO(b'{"detail":"pi timed out"}'))

    client = AgentJudgeClient(AgentJudgeClientConfig(url="http://stub:9999"), _failing_opener)
    with pytest.raises(InvalidJudgeOutput, match="422"):
        client.compare("c-err", CANDIDATES, "Which is better?")
