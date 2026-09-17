import json
import subprocess

import pytest

from octagon_evals.errors import InvalidJudgeOutput
from octagon_evals.judge_service.config import JudgeServiceConfig
from octagon_evals.judge_service.pi_runner import PiRunner, _last_assistant_text


def _events(final_text, *, include_agent_end=True):
    events = [
        {"type": "session", "version": 3, "id": "x"},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {"type": "message_start", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "message_start", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}]}},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 1, "delta": final_text}},
        {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": final_text}]}},
        {"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": final_text}], "toolResults": []}},
    ]
    if include_agent_end:
        events.append({
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": final_text}]},
            ],
            "willRetry": False,
        })
    events.append({"type": "agent_settled"})
    return "\n".join(json.dumps(e) for e in events)


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_runner(stdout, stderr="", returncode=0):
    return lambda cmd, **kwargs: _FakeCompletedProcess(stdout, stderr, returncode)


def test_pi_runner_extracts_final_assistant_text_from_agent_end():
    runner = PiRunner(JudgeServiceConfig(), runner=_fake_runner(_events("world")))
    assert runner.run(prompt="hi", workspace="/tmp") == "world"


def test_pi_runner_falls_back_to_turn_end_without_agent_end():
    runner = PiRunner(
        JudgeServiceConfig(),
        runner=_fake_runner(_events("world", include_agent_end=False)),
    )
    assert runner.run(prompt="hi", workspace="/tmp") == "world"


def test_pi_runner_takes_last_assistant_message_after_tool_use():
    agent_end = {
        "type": "agent_end",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "ls"}}]},
            {"role": "toolResult", "toolCallId": "c1", "toolName": "bash", "content": [{"type": "text", "text": "evidence.json"}]},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "seen"}, {"type": "text", "text": "verdict json"}]},
        ],
        "willRetry": False,
    }
    events = _events("first", include_agent_end=False).splitlines()[:-1]  # drop trailing agent_settled
    ndjson = "\n".join([*events, json.dumps(agent_end), json.dumps({"type": "agent_settled"})])
    runner = PiRunner(JudgeServiceConfig(), runner=_fake_runner(ndjson))
    assert runner.run(prompt="hi", workspace="/tmp") == "verdict json"


def test_pi_runner_preserves_fenced_verdict_text_for_service_layer():
    verdict = '```json\n{"value": 0.8, "reason": "ok", "raw": {}}\n```'
    runner = PiRunner(JudgeServiceConfig(), runner=_fake_runner(_events(verdict)))
    assert runner.run(prompt="hi", workspace="/tmp") == verdict


def test_pi_runner_raises_on_empty_output():
    runner = PiRunner(JudgeServiceConfig(), runner=_fake_runner(""))
    with pytest.raises(InvalidJudgeOutput, match="no output"):
        runner.run(prompt="hi", workspace="/tmp")


def test_pi_runner_raises_on_nonzero_exit():
    runner = PiRunner(
        JudgeServiceConfig(),
        runner=_fake_runner("", stderr="boom", returncode=1),
    )
    with pytest.raises(InvalidJudgeOutput, match="exited 1"):
        runner.run(prompt="hi", workspace="/tmp")


def test_pi_runner_raises_on_timeout():
    def timeout_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    runner = PiRunner(JudgeServiceConfig(timeout=0.01), runner=timeout_runner)
    with pytest.raises(InvalidJudgeOutput, match="timed out"):
        runner.run(prompt="hi", workspace="/tmp")


def test_pi_runner_raises_when_pi_binary_is_missing():
    def missing_runner(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    runner = PiRunner(JudgeServiceConfig(pi_bin="missing-pi"), runner=missing_runner)
    with pytest.raises(InvalidJudgeOutput, match="unable to start pi"):
        runner.run(prompt="hi", workspace="/tmp")


def test_last_assistant_text_skips_thinking():
    messages = [
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "noise"}, {"type": "text", "text": "answer"}]},
    ]
    assert _last_assistant_text(messages) == "answer"


def test_build_command_defaults_to_json_print_no_session_and_read_tools():
    runner = PiRunner(JudgeServiceConfig())
    cmd = runner._build_command("evaluate")
    assert cmd[:5] == ["pi", "--mode", "json", "--print", "--no-session"]
    assert "--tools" in cmd and "read,bash" in cmd
    assert "--system-prompt" in cmd
    assert cmd[-1] == "evaluate"


def test_build_command_includes_provider_model_and_thinking_when_set():
    config = JudgeServiceConfig(provider="stealth", model="ox-alpha", thinking="off")
    cmd = PiRunner(config)._build_command("evaluate")
    assert "--provider" in cmd and "stealth" in cmd
    assert "--model" in cmd and "ox-alpha" in cmd
    assert "--thinking" in cmd and "off" in cmd
