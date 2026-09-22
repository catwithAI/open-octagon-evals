"""JEV pairwise 适配器：eligibility（上下文上限）、winner choice 判题映射。"""
import json
from pathlib import Path

import pytest

from octagon_evals.calibration.jev_pairwise import JevPairwiseJudge
from octagon_evals.calibration.rubricbench import build_user_prompt, load_cases
from octagon_evals.scorers.jev import SystemOneConfig

FIXTURE = Path(__file__).parents[1] / "fixtures/rubricbench_sample.json"


class _FakeClient:
    def __init__(self, choice=None, answers=None):
        self.choice = choice
        self.answers = answers or {}
        self.calls = []
    def judge(self, *, state, questions):
        self.calls.append((state, questions))
        if self.choice is not None:
            return {"winner": {"type": "choice", "choice": self.choice}}
        return self.answers


def _judge(choice=None, answers=None):
    config = SystemOneConfig(url="http://x:8100", model="kev-4b")
    return JevPairwiseJudge(config=config, client=_FakeClient(choice=choice, answers=answers))


def test_winner_question_shape():
    judge = _judge(choice="a")
    case = load_cases(FIXTURE)[0]
    judge.judge(case)
    state, questions = judge.client.calls[0]
    # state = 官方模板（instruction + checklist + A + B）
    assert "[The User's Original <Instruction>]" in state
    assert "[The Evaluation <Checklist>]" in state and "[The Start of Assistant A's <Response>]" in state
    assert "[The Start of Assistant B's <Response>]" in state
    winner = questions["winner"]
    assert winner["type"] == "choice"
    assert set(winner["criteria"]) == {"a", "b"}


def test_verdict_mapping():
    for choice, want in [("a", 0), ("b", 1), ("other", None), (None, None)]:
        judge = _judge(choice=choice)
        verdict, _ = judge.judge(load_cases(FIXTURE)[0])
        assert verdict == want, choice


def test_eligible_filters_oversized():
    judge = _judge(choice="a")
    cases = load_cases(FIXTURE)
    assert all(judge.eligible(c) for c in cases)
    # 手工构造超限 case
    big = cases[0]
    oversized = type("C", (), {
        **{k: getattr(big, k) for k in ("case_id", "instruction", "response_a", "response_b", "label", "rubrics", "source", "domain", "group")},
    })
    huge = "x" * 20000
    oversized.instruction, oversized.response_a, oversized.response_b = huge, huge, huge
    assert len(build_user_prompt(oversized)) > 10500
    assert not judge.eligible(oversized)
