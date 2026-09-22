from __future__ import annotations
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..errors import InvalidJudgeOutput
from ..models import DimensionScore
from .base import parse_score
from .comparison import validate_ranking, validate_winner

_COMPARE_SYSTEM = (
    "You are a strict pairwise evaluation judge. Each candidate's evidence is "
    "available in the current directory, under a folder named by candidate id "
    "(for example run-a/ and run-b/). Read each candidate's evidence "
    "separately before comparing them on the given question. The candidate "
    "labels and their order are arbitrary — ignore position and judge purely "
    "by substance. Return a single JSON object with keys winner, reason, raw. "
    "winner is exactly one of the two candidate ids, or the string 'tie'."
)

_RANK_SYSTEM = (
    "You are a strict listwise evaluation judge. Every candidate's evidence is "
    "available in the current directory, under a folder named by candidate id. "
    "Browse all candidates before deciding; position in the list carries no "
    "signal. Return a single JSON object with keys ranking, reason, raw. "
    "ranking is an array of every candidate id, best first, exactly once each."
)


@dataclass(frozen=True)
class AgentJudgeClientConfig:
    url: str = "http://127.0.0.1:8001"
    timeout: float = 330.0

    @classmethod
    def from_env(cls) -> "AgentJudgeClientConfig":
        return cls(
            os.getenv("OCTAGON_JUDGE_SERVICE_URL", "http://127.0.0.1:8001"),
            float(os.getenv("OCTAGON_JUDGE_CLIENT_TIMEOUT", "330")),
        )


class AgentJudgeClient:
    """Agent-as-judge 后端：HTTP 客户端，驱动独立的 pi Judge 服务。

    实现 JudgeBackend 协议：score / compare / rank。服务是无感知方法的
    通用执行器；方法级 system prompt 与工作区布局由本类拼好传过去，
    比较语义的校验在这里完成。``compare`` 与 ``rank`` 的 task_id 去重
    保证每 pair / 每次 rank 只调用一次。
    """

    def __init__(self, config: AgentJudgeClientConfig, opener=urlopen):
        self.config = config
        self.opener = opener
        self.calls = 0
        self._called_tasks: set[str] = set()

    def score(self, task_id: str, evidence: dict, dimension_question: str,
              *, anchors=None, output_schema=None) -> DimensionScore:
        if task_id in self._called_tasks:
            raise RuntimeError("agent judge is single-call per dimension")
        payload = {
            "task_id": task_id,
            "dimension_question": dimension_question,
            "anchors": anchors or [],
            "output_schema": output_schema or {},
            "evidence": evidence,
            "lineage": {},
        }
        body = self._post(payload)
        verdict = body.get("result") if isinstance(body.get("result"), dict) else body
        score = parse_score(task_id, verdict, "agent_judge_agentic", body.get("lineage", {}))
        self._called_tasks.add(task_id)
        self.calls += 1
        return score

    def compare(self, task_id: str, candidates: list[dict], dimension_question: str,
                *, anchors=None, allow_ties: bool = True, output_schema=None) -> dict:
        if task_id in self._called_tasks:
            raise RuntimeError("agent judge is single-call per pair")
        if len(candidates) != 2:
            raise ValueError("pairwise judge requires exactly two candidates")
        run_a, run_b = candidates[0]["id"], candidates[1]["id"]
        verdict = self._judge(
            task_id,
            candidates,
            dimension_question,
            anchors=anchors,
            required=["winner", "reason", "raw"],
            system_prompt=_COMPARE_SYSTEM,
            output_schema=output_schema,
        )
        # 裁决以 run id 表示（或 'tie'），不做呈现顺序归一化；语义校验在主体 scorer。
        validate_winner(verdict, run_a, run_b, allow_ties=allow_ties)
        self._called_tasks.add(task_id)
        self.calls += 1
        return {"winner": verdict["winner"], "reason": verdict.get("reason"), "raw": verdict.get("raw")}

    def rank(self, task_id: str, candidates: list[dict], dimension_question: str,
             *, anchors=None, output_schema=None) -> dict:
        if task_id in self._called_tasks:
            raise RuntimeError("agent judge is single-call per rank")
        if len(candidates) < 2:
            raise ValueError("listwise judge requires at least two candidates")
        verdict = self._judge(
            task_id,
            candidates,
            dimension_question,
            anchors=anchors,
            required=["ranking", "reason", "raw"],
            system_prompt=_RANK_SYSTEM,
            output_schema=output_schema,
        )
        run_ids = [c["id"] for c in candidates]
        ranking = validate_ranking(verdict, run_ids)
        self._called_tasks.add(task_id)
        self.calls += 1
        return {"ranking": ranking, "reason": verdict.get("reason"), "raw": verdict.get("raw")}

    def _judge(self, task_id, candidates, dimension_question, *, anchors, required,
               system_prompt, output_schema) -> dict:
        files: dict[str, object] = {}
        for candidate in candidates:
            for key, value in candidate["evidence"].items():
                files[f"{candidate['id']}/{key}"] = value
        payload = {
            "task_id": task_id,
            "dimension_question": dimension_question,
            "anchors": anchors or [],
            "output_schema": output_schema or {"type": "object", "required": required},
            "evidence": {c["id"]: c["evidence"] for c in candidates},
            "system_prompt": system_prompt,
            "files": files,
            "lineage": {},
        }
        body = self._post(payload)
        verdict = body.get("result")
        if not isinstance(verdict, dict):
            raise ValueError("judge service returned no structured result")
        return verdict

    def _post(self, payload: dict) -> dict:
        request = Request(
            f"{self.config.url}/judge",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.config.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            # judge 服务的技术失败（pi 超时、输出非法等）返回 4xx/5xx；
            # 转成领域错误，由上层干净地失败并允许重试，而不是崩掉调用链。
            detail = ""
            try:
                detail = exc.read().decode()[:200]
            except Exception:
                pass
            raise InvalidJudgeOutput(f"judge service error {exc.code}: {detail}") from exc
