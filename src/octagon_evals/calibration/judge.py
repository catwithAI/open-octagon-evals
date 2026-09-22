"""Judge transport：用官方 prompt 驱动配置的 judge，返回原始文本。

校准走 judge 的 transport，不进评分方法层：agentic 复用
``judge_service/pi_runner.PiRunner``（--no-tools，响应内联），inline 复用
``scorers/agent_judge.AgentJudgeConfig`` 直连 OpenAI-compatible 端点。
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..errors import InvalidJudgeOutput
from ..judge_service.config import JudgeServiceConfig
from ..judge_service.pi_runner import PiRunner
from ..scorers.agent_judge import AgentJudgeConfig


@dataclass(frozen=True)
class JudgeIdentity:
    backend: str  # "agentic" | "inline"
    model: str
    provider: str | None
    prompt_version: str


class JudgeTransport:
    """在指定后端上用 ``system_prompt`` + ``user_prompt`` 跑一次 judge。

    注入点：``subprocess_runner``（agentic 底层 pi 调用，测试用）、``opener``
    （inline 测试）、两个 config。不注入时从环境读取（OCTAGON_JUDGE_*）。
    """

    def __init__(
        self,
        *,
        agentic_config: JudgeServiceConfig | None = None,
        inline_config: AgentJudgeConfig | None = None,
        subprocess_runner=subprocess.run,
        opener=urlopen,
        timeout: float = 300.0,
    ):
        self.agentic_config = agentic_config
        self.inline_config = inline_config
        self.subprocess_runner = subprocess_runner
        self.opener = opener
        self.timeout = timeout
        self.calls = 0
        self._lock = threading.Lock()

    def _count_call(self):
        with self._lock:
            self.calls += 1

    def judge(self, *, backend: str, system_prompt: str, user_prompt: str) -> tuple[str, JudgeIdentity]:
        if backend == "agentic":
            return self._agentic(system_prompt, user_prompt)
        if backend == "inline":
            return self._inline(system_prompt, user_prompt)
        raise ValueError(f"unknown judge backend: {backend}")

    def _agentic(self, system_prompt: str, user_prompt: str) -> tuple[str, JudgeIdentity]:
        config = self.agentic_config or JudgeServiceConfig.from_env()
        # rubricbench 响应内联，无需检索工具；覆盖为 --no-tools 省钱。
        config = dataclasses.replace(config, tools=())
        runner = PiRunner(config, runner=self.subprocess_runner)
        workspace = tempfile.mkdtemp(prefix="octagon-calibration-")
        try:
            text = runner.run(prompt=user_prompt, workspace=workspace, system_prompt=system_prompt)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        self._count_call()
        return text, JudgeIdentity("agentic", config.model or "pi-default", config.provider, config.prompt_version)

    def _inline(self, system_prompt: str, user_prompt: str) -> tuple[str, JudgeIdentity]:
        config = self.inline_config or AgentJudgeConfig.from_env()
        payload = {
            "model": config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
        request = Request(config.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except HTTPError as exc:
            raise InvalidJudgeOutput(f"inline judge error {exc.code}: {exc.reason}") from exc
        content = body["choices"][0]["message"]["content"]
        self._count_call()
        return content, JudgeIdentity("inline", config.model, None, config.prompt_version)
