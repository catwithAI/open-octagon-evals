"""Judge transport：agentic（pi）与 inline（OpenAI-compatible）的官方 prompt 注入。"""
import json

from octagon_evals.calibration.judge import JudgeTransport
from octagon_evals.calibration.rubricbench import RUBRICBENCH_SYSTEM_PROMPT
from octagon_evals.judge_service.config import JudgeServiceConfig
from octagon_evals.scorers.agent_judge import AgentJudgeConfig

SYSTEM = RUBRICBENCH_SYSTEM_PROMPT
USER = "user prompt content"


def _event_stream(text):
    events = [
        {"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "toolResults": []}},
        {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": text}]}]},
    ]
    return "\n".join(json.dumps(e) for e in events)


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class _FakeResponse:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def test_agentic_transport_injects_official_prompts_and_no_tools():
    captured = {}

    def runner(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompletedProcess(_event_stream("[[A]]"))

    config = JudgeServiceConfig(pi_bin="pi", provider="deepseek", model="deepseek-flash")
    transport = JudgeTransport(agentic_config=config, subprocess_runner=runner)

    text, identity = transport.judge(backend="agentic", system_prompt=SYSTEM, user_prompt=USER)

    assert text == "[[A]]"
    cmd = captured["cmd"]
    assert cmd[-2] == SYSTEM and cmd[-1] == USER
    assert "--no-tools" in cmd
    assert identity.backend == "agentic" and identity.model == "deepseek-flash" and identity.provider == "deepseek"
    assert transport.calls == 1


def test_inline_transport_injects_official_messages_and_auth():
    class FakeOpener:
        def __init__(self):
            self.request = None
        def __call__(self, request, **kwargs):
            self.request = request
            body = json.dumps({"choices": [{"message": {"content": "[[B]]"}}]}).encode()
            return _FakeResponse(body)

    opener = FakeOpener()
    config = AgentJudgeConfig(endpoint="https://example.test/v1/chat/completions", model="judge-m", api_key="secret")
    transport = JudgeTransport(inline_config=config, opener=opener)

    text, identity = transport.judge(backend="inline", system_prompt=SYSTEM, user_prompt=USER)

    assert text == "[[B]]"
    payload = json.loads(opener.request.data)
    assert payload["model"] == "judge-m" and payload["temperature"] == 0
    assert payload["messages"][0] == {"role": "system", "content": SYSTEM}
    assert payload["messages"][1] == {"role": "user", "content": USER}
    assert opener.request.headers["Authorization"] == "Bearer secret"
    assert identity.backend == "inline" and identity.model == "judge-m"


def test_transport_rejects_unknown_backend():
    transport = JudgeTransport()
    try:
        transport.judge(backend="bogus", system_prompt=SYSTEM, user_prompt=USER)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
