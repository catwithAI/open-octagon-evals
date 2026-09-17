from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeServiceConfig:
    pi_bin: str = "pi"
    provider: str | None = None
    model: str | None = None
    prompt_version: str = "agentic-1"
    timeout: float = 300.0
    tools: tuple[str, ...] = ("read", "bash")
    workspace_base: str | None = None
    thinking: str = "off"

    @classmethod
    def from_env(cls) -> "JudgeServiceConfig":
        return cls(
            pi_bin=os.getenv("OCTAGON_JUDGE_PI_BIN", cls.pi_bin),
            provider=os.getenv("OCTAGON_JUDGE_PROVIDER") or None,
            model=os.getenv("OCTAGON_JUDGE_MODEL") or None,
            prompt_version=os.getenv("OCTAGON_JUDGE_PROMPT_VERSION", "agentic-1"),
            timeout=float(os.getenv("OCTAGON_JUDGE_TIMEOUT", str(cls.timeout))),
            tools=tuple(t for t in os.getenv("OCTAGON_JUDGE_TOOLS", "read,bash").split(",") if t),
            workspace_base=os.getenv("OCTAGON_JUDGE_WORKSPACE_BASE") or None,
            thinking=os.getenv("OCTAGON_JUDGE_THINKING") or cls.thinking,
        )
