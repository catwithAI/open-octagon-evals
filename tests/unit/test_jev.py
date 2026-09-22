"""JEV 后端：SystemOneClient、JevJudge 值转换、state 解析、plan 校验。"""
import json

import pytest

from octagon_evals.errors import InvalidJudgeOutput, PlanError
from octagon_evals.models import Dimension, EvalPlan
from octagon_evals.plan.validator import validate_plan
from octagon_evals.scorers.jev import (
    JevJudge,
    SystemOneClient,
    SystemOneConfig,
    _question_verdict,
    resolve_state,
)


class _FakeResponse:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *exc): return False


class _FakeOpener:
    def __init__(self, body): self.body = body; self.request = None
    def __call__(self, request, **kwargs):
        self.request = request
        return _FakeResponse(self.body)


# ---------- SystemOneClient ----------

def test_client_parses_answers():
    opener = _FakeOpener(json.dumps({"answers": {"q": {"type": "score", "score": 0.8}}}).encode())
    client = SystemOneClient(SystemOneConfig(url="http://x:8100", model="m"), opener=opener)
    answers = client.judge(state="s", questions={"q": {"type": "score"}})
    assert answers["q"]["score"] == 0.8
    payload = json.loads(opener.request.data)
    assert payload["model"] == "m" and payload["state"] == "s"
    assert opener.request.full_url.endswith("/v1/systemone")


def test_client_missing_answers_raises():
    opener = _FakeOpener(json.dumps({"model": "m"}).encode())
    client = SystemOneClient(SystemOneConfig(), opener=opener)
    with pytest.raises(InvalidJudgeOutput):
        client.judge(state="s", questions={})


def test_client_http_error_raises():
    class Boom(Exception):
        pass
    class BadOpener:
        def __call__(self, request, **kwargs):
            from urllib.error import HTTPError
            raise HTTPError(request.full_url, 500, "boom", {}, None)
    client = SystemOneClient(SystemOneConfig(), opener=BadOpener())
    with pytest.raises(InvalidJudgeOutput):
        client.judge(state="s", questions={})


# ---------- state 解析 ----------

def test_resolve_state_string_hits_evidence_keys():
    assert resolve_state({"final_answer": "385", "artifact": "x"}, ("artifact",)) == "x"
    assert resolve_state({"final_answer": "385"}, ("missing", "final_answer")) == "385"
    # 无 evidence_keys 且没有 final_answer/answer/artifact_text → json 兜底
    assert resolve_state({"artifact": "plain"}, ()) == '{"artifact": "plain"}'


def test_resolve_state_fallbacks():
    # artifact 是 dict（snapshot_ref）→ 跳过，json 兜底
    state = resolve_state({"artifact": {"snapshot_ref": "s", "content_hash": "h"}}, ("artifact",))
    assert "snapshot_ref" in state and isinstance(state, str)
    assert resolve_state("plain") == "plain"
    assert resolve_state(123)  # json 兜底不崩
    # 超长截断
    long = resolve_state({"final_answer": "x" * 10000}, ())
    assert len(long) <= 3000


# ---------- 值转换 ----------

def test_question_verdict_types():
    assert _question_verdict("q", {"type": "score"}, {"type": "score", "score": 0.9})[0] == 0.9
    with pytest.raises(InvalidJudgeOutput):
        _question_verdict("q", {"type": "score"}, {"type": "score", "score": 1.5})
    # choice + expected
    v, rec = _question_verdict("q", {"type": "choice", "expected": "yes"}, {"type": "choice", "choice": "yes"})
    assert v == 1.0
    v, _ = _question_verdict("q", {"type": "choice", "expected": "yes"}, {"type": "choice", "choice": "no"})
    assert v == 0.0
    # choice 无 expected → diagnostic
    v, rec = _question_verdict("q", {"type": "choice"}, {"type": "choice", "choice": "yes"})
    assert v is None and rec["type"] == "choice"
    # noul → 1 - noul
    assert _question_verdict("q", {"type": "noul"}, {"type": "noul", "noul": 0.2})[0] == 0.8
    with pytest.raises(InvalidJudgeOutput):
        _question_verdict("q", {"type": "noul"}, {"type": "noul", "noul": 2.0})
    with pytest.raises(InvalidJudgeOutput):
        _question_verdict("q", {"type": "bogus"}, {"type": "bogus"})


# ---------- JevJudge.score ----------

class _FakeClient:
    def __init__(self, answers): self.answers = answers; self.state = None
    def judge(self, *, state, questions):
        self.state = state
        return self.answers


def _judge(answers, questions, evidence=None):
    config = SystemOneConfig(url="http://x:8100", model="m")
    return JevJudge(config=config, client=_FakeClient(answers)).score(
        "t1", evidence or {"final_answer": "385"}, "q",
        evidence_keys=("artifact",), jev_questions=questions,
    )


def test_jev_score_mixed_mean():
    score = _judge(
        {"a": {"type": "score", "score": 0.9}, "b": {"type": "choice", "choice": "yes"}},
        {"a": {"type": "score", "instructions": "ok"}, "b": {"type": "choice", "instructions": "ok", "expected": "yes"}},
    )
    assert abs(score.value - 0.95) < 1e-9
    assert score.source == "jev_judge"
    assert score.raw["state"] == "385"
    assert score.lineage["model"] == "m"


def test_jev_score_diagnostic_excluded():
    score = _judge(
        {"a": {"type": "score", "score": 0.6}, "b": {"type": "choice", "choice": "whatever"}},
        {"a": {"type": "score", "instructions": "ok"}, "b": {"type": "choice", "instructions": "ok"}},
    )
    assert abs(score.value - 0.6) < 1e-9  # choice 无 expected → diagnostic 不进均值


def test_jev_score_all_diagnostic_zero():
    score = _judge(
        {"b": {"type": "choice", "choice": "whatever"}},
        {"b": {"type": "choice", "instructions": "ok"}},
    )
    assert score.value == 0.0


def test_jev_score_requires_questions():
    config = SystemOneConfig()
    judge = JevJudge(config=config, client=_FakeClient({}))
    with pytest.raises(InvalidJudgeOutput):
        judge.score("t", {"final_answer": "x"}, "q", evidence_keys=(), jev_questions=None)


def test_jev_score_missing_answer_raises():
    config = SystemOneConfig()
    judge = JevJudge(config=config, client=_FakeClient({"a": {"type": "score", "score": 0.5}}))
    with pytest.raises(InvalidJudgeOutput):
        judge.score("t", {"final_answer": "x"}, "q", evidence_keys=(),
                    jev_questions={"a": {"type": "score"}, "b": {"type": "score"}})


# ---------- plan 校验 ----------

def _plan(dims):
    return EvalPlan(1, 1, tuple(dims))


def test_validate_jev_plan_ok():
    d = Dimension("answer_quality", method="jev_judge", weight=1.0, jev_questions={
        "correctness": {"type": "score", "instructions": "ok", "criteria": {"low": "no", "high": "yes"}},
        "computed": {"type": "choice", "instructions": "ok", "criteria": {"yes": "y", "no": "n"}, "expected": "yes"},
    })
    validate_plan(_plan((d,)))


def test_validate_jev_requires_questions():
    d = Dimension("answer_quality", method="jev_judge", weight=1.0)
    with pytest.raises(PlanError):
        validate_plan(_plan((d,)))


def test_validate_jev_invalid_question():
    d = Dimension("answer_quality", method="jev_judge", weight=1.0, jev_questions={
        "q": {"type": "decomposition", "instructions": "ok"},
    })
    with pytest.raises(PlanError):
        validate_plan(_plan((d,)))


def test_validate_jev_score_needs_criteria():
    d = Dimension("answer_quality", method="jev_judge", weight=1.0, jev_questions={
        "q": {"type": "score", "instructions": "ok"},
    })
    with pytest.raises(PlanError):
        validate_plan(_plan((d,)))
