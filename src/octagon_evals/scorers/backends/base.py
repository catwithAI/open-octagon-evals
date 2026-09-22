"""Judge 后端协议。

方法语义（pointwise / pairwise / listwise）留在主体 scorers；
后端只负责"拿到裁决"。协议按方法分三个入口，让每个后端对每种方法
各自特化 prompt / 工作区 / 预算，而不是挤进一个通用 judge()。

实现：
- InlineJudge（``octagon_evals.scorers.agent_judge``）：OpenAI-compatible 单次调用；
- AgenticJudge（``octagon_evals.scorers.agent_judge_client``）：驱动 pi Judge 服务。
"""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class JudgeBackend(Protocol):
    """judge 后端的统一入口。所有方法只依赖提供的证据，返回可校验的裁决。"""

    def score(self, task_id: str, evidence: dict[str, Any], question: str,
              *, anchors=None, output_schema=None) -> Any:
        """pointwise：单候选裁决，返回 DimensionScore（含校验后的 value）。"""

    def compare(self, task_id: str, candidates: list[dict[str, Any]], question: str,
                *, anchors=None, allow_ties: bool = True, output_schema=None) -> dict[str, Any]:
        """pairwise：两个候选的裁决，返回 {winner, reason, raw}。"""

    def rank(self, task_id: str, candidates: list[dict[str, Any]], question: str,
             *, anchors=None, output_schema=None) -> dict[str, Any]:
        """listwise：多候选的裁决，返回 {ranking, reason, raw}。"""
