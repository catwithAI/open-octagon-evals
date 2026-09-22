import json, pytest
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig

class Response:
    def __init__(self,p): self.p=p
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self): return json.dumps({"choices":[{"message":{"content":json.dumps(self.p)}}]}).encode()

class CapturingOpener:
    def __init__(self, payload): self.payload = payload; self.request = None
    def __call__(self, request, *, timeout=None):
        self.request = request
        return Response(self.payload)

def test_agent_judge_defaults_to_free_model_and_calls_once():
    judge=AgentJudge(AgentJudgeConfig(), lambda req, **kw: Response({"value":.7,"reason":"ok"}))
    assert judge.config.model == "stealth/ox-alpha"; assert judge.score("t",{},"quality").value == .7
    with pytest.raises(RuntimeError): judge.score("t",{},"quality")

def test_agent_judge_prompt_contains_structured_anchors_and_schema():
    opener = CapturingOpener({"value": .8, "reason": "two checks passed"})
    judge = AgentJudge(AgentJudgeConfig(), opener)
    judge.score(
        "task-structured",
        {"candidate_output": "concrete details"},
        "Check the plan.",
        anchors=[{"id": "agent", "pass_if": "a concrete agent name is present"}],
        output_schema={"type": "object", "required": ["value", "reason", "raw"]},
    )
    request = json.loads(opener.request.data)
    assert "strict evaluation judge" in request["messages"][0]["content"]
    user = json.loads(request["messages"][1]["content"])
    assert user["anchors"][0]["id"] == "agent"
    assert user["output_schema"]["required"] == ["value", "reason", "raw"]


class RawResponse:
    """Opener that returns judge content verbatim (not re-encoded as JSON)."""
    def __init__(self, content): self.content = content
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()


@pytest.mark.parametrize("content", [
    '{"value": 0.5, "reason": "plain json", "raw": {}}',
    '```json\n{"value": 0.5, "reason": "fenced", "raw": {}}\n```',
    '```\n{"value": 0.5, "reason": "bare fence", "raw": {}}\n```',
    'Here is my verdict:\n{"value": 0.5, "reason": "prose first", "raw": {}}',
])
def test_agent_judge_accepts_common_json_wrappers(content):
    """Chat models fence their JSON or prefix it with prose even when told not to.

    Before this, any of these came back as `Expecting value: line 1 column 1`
    and surfaced as a 422 — indistinguishable from a malformed request.
    """
    judge = AgentJudge(AgentJudgeConfig(), lambda req, **kw: RawResponse(content))
    assert judge.score("t-wrap-" + content[:12], {}, "quality").value == 0.5


def test_agent_judge_rejects_unparseable_output_instead_of_guessing():
    from octagon_evals.errors import InvalidJudgeOutput
    judge = AgentJudge(AgentJudgeConfig(), lambda req, **kw: RawResponse("I cannot score this."))
    with pytest.raises(InvalidJudgeOutput):
        judge.score("t-prose", {}, "quality")


def test_agent_judge_accumulates_usage_and_forwards_timeout():
    """usage 从 LLM 响应回读累加；单次调用 timeout 随 opener 注入。"""
    requests = []

    class _LLMResponse:
        def __init__(self, body): self._body = body
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(self._body).encode()

    def opener(request, *, timeout=None):
        requests.append((json.loads(request.data), timeout))
        return _LLMResponse({
            "choices": [{"message": {"content": json.dumps({"value": 0.4, "reason": "partial"})}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })

    judge = AgentJudge(AgentJudgeConfig(timeout=42.0), opener)
    assert judge.score("t-usage-1", {}, "quality").value == 0.4
    assert judge.score("t-usage-2", {}, "quality").value == 0.4
    assert judge.usage == {"prompt_tokens": 22, "completion_tokens": 14, "total_tokens": 36}
    assert requests[0][1] == 42.0


def test_agent_judge_config_timeout_from_env(monkeypatch):
    monkeypatch.setenv("OCTAGON_JUDGE_TIMEOUT", "9")
    assert AgentJudgeConfig.from_env().timeout == 9.0
