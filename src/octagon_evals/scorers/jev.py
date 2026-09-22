"""JEV-as-judge：实验性 pointwise 方法。

内网 System One 开源模型（JEV 类）：``POST /v1/systemone``，输入 ``state``
（被评文本）+ 结构化 ``questions``（choice/score/noul），返回每 question 的
结构化裁决。questions 由 plan 在 ``dimension.jev_questions`` 显式声明，
``expected``（choice 的期望选择）是我们加在 question 上的评分约定，API 透传
忽略。

**纯增量实验**：不触碰 ``agent_judge`` / ``agent_judge_agentic`` / pairwise /
listwise 的任何代码路径。见 docs/jev-judge.md。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..errors import InvalidJudgeOutput
from .base import parse_score

JEV_PROMPT_VERSION = "jev-v1"
# laya-multilingual 1024 token ctx 的保守字符上限；长 state 简单截断。
STATE_MAX_CHARS = 3000

_VALID_TYPES = ("choice", "score", "noul")


@dataclass(frozen=True)
class SystemOneConfig:
    url: str = "http://192.168.130.23:8100"
    model: str = "laya-multilingual"
    timeout: float = 30.0
    prompt_version: str = JEV_PROMPT_VERSION

    @classmethod
    def from_env(cls) -> "SystemOneConfig":
        return cls(
            os.getenv("OCTAGON_JEV_URL", cls.url),
            os.getenv("OCTAGON_JEV_MODEL", cls.model),
            float(os.getenv("OCTAGON_JEV_TIMEOUT", str(cls.timeout))),
            os.getenv("OCTAGON_JEV_PROMPT_VERSION", cls.prompt_version),
        )


class SystemOneClient:
    """调内网 System One API；测试可注入 fake opener。"""

    def __init__(self, config: SystemOneConfig, opener=urlopen):
        self.config = config
        self.opener = opener

    def judge(self, *, state: str, questions: dict) -> dict:
        endpoint = self.config.url.rstrip("/") + "/v1/systemone"
        payload = {"model": self.config.model, "state": state, "questions": questions}
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.config.timeout) as response:
                body = json.loads(response.read())
        except HTTPError as exc:
            raise InvalidJudgeOutput(f"systemone error {exc.code}: {exc.reason}") from exc
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise InvalidJudgeOutput("systemone response missing answers")
        return answers


def resolve_state(evidence, evidence_keys=()) -> str:
    """实验性 state 解析：按 evidence_keys 命中的第一个字符串值；否则依次取
    final_answer / answer / artifact_text；再否则 json 兜底。超长截断。"""
    def _as_text(value) -> str | None:
        if isinstance(value, str) and value.strip():
            return value
        return None

    if isinstance(evidence, dict):
        for key in (*evidence_keys, "final_answer", "answer", "artifact_text"):
            text = _as_text(evidence.get(key))
            if text is not None:
                return text[:STATE_MAX_CHARS]
        return json.dumps(evidence, ensure_ascii=False)[:STATE_MAX_CHARS]
    if isinstance(evidence, str):
        return evidence[:STATE_MAX_CHARS]
    return json.dumps(evidence, ensure_ascii=False)[:STATE_MAX_CHARS]


def _question_verdict(name: str, question: dict, answer: dict) -> tuple[float | None, dict]:
    """返回 (scored value 或 None=diagnostic, 该问判定记录)。"""
    qtype = answer.get("type") or question.get("type")
    if qtype not in _VALID_TYPES:
        raise InvalidJudgeOutput(f"jev question {name}: unknown type {qtype!r}")
    if qtype == "score":
        score = answer.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            raise InvalidJudgeOutput(f"jev question {name}: score out of range: {score!r}")
        return float(score), {"type": "score", "score": float(score), "confidence": answer.get("confidence")}
    if qtype == "choice":
        choice = answer.get("choice")
        verdict = {"type": "choice", "choice": choice, "confidence": answer.get("confidence")}
        expected = question.get("expected")
        if expected is None:
            return None, verdict  # diagnostic：无期望选择，不进入均值
        return (1.0 if choice == expected else 0.0), verdict
    # noul
    noul = answer.get("noul")
    if not isinstance(noul, (int, float)) or isinstance(noul, bool) or not 0 <= noul <= 1:
        raise InvalidJudgeOutput(f"jev question {name}: noul out of range: {noul!r}")
    return float(1 - noul), {"type": "noul", "noul": float(noul), "confidence": answer.get("confidence")}


class JevJudge:
    """JEV 后端：evidence + dimension.jev_questions → [0,1] 值。

    对齐 ``AgentJudge`` 的注入风格；``config``/``client`` 可注入（测试用）。
    """

    def __init__(self, config: SystemOneConfig | None = None, client: SystemOneClient | None = None):
        self.config = config or SystemOneConfig.from_env()
        self.client = client or SystemOneClient(self.config)

    def score(
        self,
        task_id: str,
        evidence,
        dimension_question: str,
        *,
        anchors=None,
        output_schema=None,
        evidence_keys=(),
        jev_questions=None,
    ):
        if not isinstance(jev_questions, dict) or not jev_questions:
            raise InvalidJudgeOutput("jev_judge requires declared jev_questions")
        state = resolve_state(evidence, evidence_keys)
        answers = self.client.judge(state=state, questions=jev_questions)

        scored: list[float] = []
        verdicts: dict[str, dict] = {}
        for name, question in jev_questions.items():
            answer = answers.get(name)
            if not isinstance(answer, dict):
                raise InvalidJudgeOutput(f"systemone missing answer for question {name!r}")
            value, verdict = _question_verdict(name, question, answer)
            verdicts[name] = verdict
            if value is not None:
                scored.append(value)

        value = sum(scored) / len(scored) if scored else 0.0
        reason = "; ".join(
            f"{name}={v['type']}:"
            + (f"{v['score']:.3f}" if v["type"] == "score" else str(v.get("choice", "")) if v["type"] == "choice" else f"{v['noul']:.3f}")
            for name, v in verdicts.items()
        )
        lineage = {
            "model": self.config.model,
            "api": self.config.url,
            "prompt_version": self.config.prompt_version,
        }
        raw = {"state": state, "questions": jev_questions, "answers": answers, "verdicts": verdicts}
        return parse_score(task_id, {"value": value, "reason": reason, "raw": raw}, "jev_judge", lineage)
