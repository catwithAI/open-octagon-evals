"""JEV（System One）pairwise 校准适配器：单次调用判 A/B 谁优。

RubricBench 是 pairwise（A/B 谁优），JEV 是结构化 questions 单次调用。做法：
``state`` = 官方模板（instruction + checklist + A + B，复用
``build_user_prompt``），加一个 ``winner`` choice question ``{a,b}``，模型
直接选哪个更好。响应独立于位置，天然无位置偏差。

上下文/请求体有限（kev-4b 实测 ~10-11KB 开始 413 抖动）：超限 case 用
``eligible()`` 排除并报 coverage，**不做截断**——截断会偏袒模板里后写的 response。
"""
from __future__ import annotations

import hashlib
import json

from ..scorers.jev import SystemOneClient, SystemOneConfig
from .rubricbench import RubricCase, build_user_prompt

JEV_PAIRWISE_PROMPT_VERSION = "jev-pairwise-v1"
# kev-4b 实测安全上限（~10-11KB 出现 413 抖动），保守取 10500 字符。
JEV_MAX_STATE_CHARS = 10500

_WINNER_QUESTION = {
    "winner": {
        "type": "choice",
        "instructions": (
            "严格按照提供的 checklist 比较 response A 与 response B，判断哪个更好。"
            "位置与顺序无关，只看实质内容。"
        ),
        "criteria": {"a": "response A 更好", "b": "response B 更好"},
    }
}


class JevPairwiseJudge:
    """JEV pairwise 判题：对每个 RubricBench case 单次调用取 winner。

    测试可注入 fake ``client``（``judge(state, questions)`` 返回 answers dict）。
    """

    def __init__(self, config: SystemOneConfig | None = None, client: SystemOneClient | None = None):
        self.config = config or SystemOneConfig.from_env()
        self.client = client or SystemOneClient(self.config)

    @property
    def prompt_hash(self) -> str:
        return hashlib.sha256(JEV_PAIRWISE_PROMPT_VERSION.encode()).hexdigest()

    def eligible(self, case: RubricCase) -> bool:
        """state（官方模板）是否在上下文/请求体安全上限内。"""
        return len(build_user_prompt(case)) <= JEV_MAX_STATE_CHARS

    def judge(self, case: RubricCase) -> tuple[int | None, dict]:
        """返回 (verdict: 0=A 优 / 1=B 优 / None=invalid, answers)。"""
        state = build_user_prompt(case)
        answers = self.client.judge(state=state, questions=_WINNER_QUESTION)
        winner = answers.get("winner") or {}
        choice = winner.get("choice")
        verdict = 0 if choice == "a" else 1 if choice == "b" else None
        return verdict, answers
