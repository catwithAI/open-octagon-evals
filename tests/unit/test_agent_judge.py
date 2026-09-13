import json, pytest
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig

class Response:
    def __init__(self,p): self.p=p
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self): return json.dumps({"choices":[{"message":{"content":json.dumps(self.p)}}]}).encode()

class CapturingOpener:
    def __init__(self, payload): self.payload = payload; self.request = None
    def __call__(self, request):
        self.request = request
        return Response(self.payload)

def test_agent_judge_defaults_to_free_model_and_calls_once():
    judge=AgentJudge(AgentJudgeConfig(), lambda req: Response({"value":.7,"reason":"ok"}))
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
