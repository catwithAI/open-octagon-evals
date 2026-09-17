from __future__ import annotations
import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen

from ..models import DimensionScore
from .base import parse_score


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
    """HTTP client for the agentic judge service.

    Mirrors the ``AgentJudge`` ``score`` signature so the eval core can swap
    between the inline single-call judge and the pi-driven service.
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
        payload = json.dumps(
            {
                "task_id": task_id,
                "dimension_question": dimension_question,
                "anchors": anchors or [],
                "output_schema": output_schema or {},
                "evidence": evidence,
                "lineage": {},
            }
        ).encode()
        request = Request(
            f"{self.config.url}/judge",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener(request, timeout=self.config.timeout) as response:
            body = json.loads(response.read())
        score = parse_score(task_id, body, "agent_judge_agentic", body.get("lineage", {}))
        self._called_tasks.add(task_id)
        self.calls += 1
        return score
