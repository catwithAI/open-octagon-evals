from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from ..errors import InvalidJudgeOutput
from .config import JudgeServiceConfig

_SYSTEM_PROMPT = (
    "You are an evaluation judge. Read the evidence files in the current "
    "directory if you need to, then answer with a single JSON object with "
    "keys value, reason, raw. value is a finite number in [0,1]. Do not "
    "explore further than necessary."
)


@dataclass
class PiRunner:
    config: JudgeServiceConfig
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run

    def run(self, *, prompt: str, workspace: str, system_prompt: str | None = None) -> str:
        """Invoke pi in the workspace and return the final assistant text.

        ``system_prompt`` overrides the default judge prompt; the service is a
        generic executor and method-level prompts come from the caller.

        Raises ``InvalidJudgeOutput`` on timeout, non-zero exit, empty output,
        or when no assistant text can be extracted.
        """
        cmd = self._build_command(prompt, system_prompt)
        try:
            result = self.runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=workspace,
            )
        except subprocess.TimeoutExpired as exc:
            raise InvalidJudgeOutput(
                f"pi timed out after {self.config.timeout}s"
            ) from exc
        except OSError as exc:
            raise InvalidJudgeOutput(f"unable to start pi: {exc}") from exc
        if result.returncode != 0:
            raise InvalidJudgeOutput(
                f"pi exited {result.returncode}: {result.stderr[:500]}"
            )
        return self._extract_final_text(result.stdout)

    def _build_command(self, prompt: str, system_prompt: str | None = None) -> list[str]:
        c = self.config
        cmd = [c.pi_bin, "--mode", "json", "--print", "--no-session"]
        if c.provider:
            cmd += ["--provider", c.provider]
        if c.model:
            cmd += ["--model", c.model]
        if c.thinking:
            cmd += ["--thinking", c.thinking]
        if c.tools:
            cmd += ["--tools", ",".join(c.tools)]
        else:
            cmd += ["--no-tools"]
        cmd += ["--system-prompt", system_prompt or _SYSTEM_PROMPT, prompt]
        return cmd

    def _extract_final_text(self, stdout: str) -> str:
        """Pull the final assistant text out of pi's NDJSON event stream.

        Priority: the last ``agent_end`` event's final assistant message, then
        the last ``turn_end`` assistant message. The last ``type:text`` content
        item wins so a trailing ``thinking`` block is not mistaken for output.
        """
        lines = stdout.strip().splitlines()
        if not lines:
            raise InvalidJudgeOutput("pi produced no output")

        agent_end_messages: list[dict[str, Any]] | None = None
        last_turn_end_message: dict[str, Any] | None = None
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            etype = event.get("type")
            if etype == "agent_end":
                agent_end_messages = event.get("messages", [])
            elif etype == "turn_end":
                message = event.get("message")
                if isinstance(message, dict) and message.get("role") == "assistant":
                    last_turn_end_message = message

        text = _last_assistant_text(agent_end_messages) if agent_end_messages else None
        if text is None and last_turn_end_message is not None:
            text = _last_assistant_text_from_message(last_turn_end_message)
        if text is None:
            raise InvalidJudgeOutput(
                f"pi output had no assistant text (tail: {stdout[-200:]!r})"
            )
        return text


def _last_assistant_text(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return _last_assistant_text_from_message(message)
    return None


def _last_assistant_text_from_message(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for item in reversed(content):
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None
