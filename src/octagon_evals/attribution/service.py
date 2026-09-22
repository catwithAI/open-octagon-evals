"""AttributionService：搭行为证据工作区 → 驱动 pi（agentic）→ 解析归因。

只 agentic：pi + `read,bash` 工具主动检索行为证据。测试可注入
``runner_factory``（用 fake subprocess runner 造 PiRunner）。
"""
from __future__ import annotations

import os
from typing import Any, Callable

from ..errors import InvalidJudgeOutput
from ..judge_service.config import JudgeServiceConfig
from ..judge_service.pi_runner import PiRunner
from ..judge_service.workspace import cleanup_workspace, create_evidence_workspace
from .role import (
    ATTRIBUTION_PROMPT_VERSION,
    ATTRIBUTION_SYSTEM_PROMPT,
    build_user_prompt,
    parse_attribution,
)


class AttributionService:
    def __init__(
        self,
        config: JudgeServiceConfig | None = None,
        *,
        runner_factory: Callable[[JudgeServiceConfig], PiRunner] | None = None,
        workspace_base: str | None = None,
    ):
        self.config = config or JudgeServiceConfig.from_env()
        self.runner_factory = runner_factory
        self.workspace_base = workspace_base
        self.calls = 0

    def attribute(self, *, dimension, score, evidence: dict[str, Any]) -> dict:
        if score is None:
            raise InvalidJudgeOutput("no resolved score to attribute")
        workspace = create_evidence_workspace(evidence, self.workspace_base)
        try:
            user_prompt = build_user_prompt(
                dimension, score,
                {"location": "evidence.json (full) / evidence/ (per-key files)"},
            )
            runner = self.runner_factory(self.config) if self.runner_factory else PiRunner(self.config)
            content = runner.run(
                prompt=user_prompt, workspace=workspace, system_prompt=ATTRIBUTION_SYSTEM_PROMPT
            )
            attribution = parse_attribution(content)
        finally:
            cleanup_workspace(workspace)
        self.calls += 1
        attribution["lineage"] = {
            "model": self.config.model or "pi-default",
            "provider": self.config.provider,
            "prompt_version": ATTRIBUTION_PROMPT_VERSION,
            "judge_service_version": os.getenv("OCTAGON_JUDGE_SERVICE_VERSION", "attribution-1"),
        }
        return attribution
