"""归因角色：ATTRIBUTION_SYSTEM_PROMPT + user prompt 构建 + 解析/校验。

模仿 agent-eval 的归因分层：输出是 `status: "candidate"` 的候选假设，供人工
复核；根因只认证据支持的，证据不足写 `insufficient_evidence`（无对照不强行
归因）；根因区分 agent_behavior / rubric / evidence / workflow。
"""
from __future__ import annotations

import json
from typing import Any

from ..errors import InvalidJudgeOutput
from ..scorers.base import parse_judge_content

ATTRIBUTION_SCHEMA_VERSION = "octagon_evals.attribution.v1"
ATTRIBUTION_PROMPT_VERSION = "attribution-v1"

_ROOT_CATEGORIES = ("agent_behavior", "rubric", "evidence", "workflow", "insufficient_evidence")
_SUGGESTION_TARGETS = ("agent", "rubric", "evidence", "workflow")
_CONFIDENCE_LEVELS = ("high", "medium", "low")

ATTRIBUTION_SYSTEM_PROMPT = """\
You are a careful attribution analyst. You are given ONE already-scored rubric dimension
and the behavior evidence of the agent that produced it. Your job is to explain the
observed outcome — the phenomenon — and its root causes, and to suggest modifications.

You may see everything a human experimenter would see: the rubric criterion and its
score anchors (the deduction points), the score the dimension received and the judge's
reason, and the agent's behavior evidence (files in the current directory — read them
with read/bash when you need to).

Follow this structure in your reply:

1. PHENOMENON — state what actually happened: the score received, and the concrete
   behavior-level observation that explains it (what the agent did or failed to do).
   Ground it in the evidence you actually read; do not invent actions.

2. ROOT CAUSES — list the genuine causes behind the phenomenon. Distinguish the
   source:
   - `agent_behavior`: the agent's choices/actions fell short (e.g. skipped a required
     step, produced an artifact that misses a criterion);
   - `rubric`: the criterion is ambiguous, contradictory, or missing a needed anchor;
   - `evidence`: the evidence provided was insufficient to verify the criterion, so the
     low score may be an observation gap, not a behavioral failure;
   - `workflow`: process/setup issues around the run.
   Rule: only claim a root cause you can support from the evidence. If the evidence is
   insufficient to determine the cause, write category `insufficient_evidence` instead
   of speculating. Do NOT force a single cause or turn a low score into a blanket
   "the agent is bad" or "the task is too hard".

3. SUGGESTIONS — concrete modifications, each with a target:
   `agent` (what the agent should do differently), `rubric` (how the criterion/anchors
   should be repaired), `evidence` (what evidence/input should change), `workflow`
   (process changes). Give the rationale for each.

This attribution is a CANDIDATE for human review, not a verdict. Never auto-apply it.

Reply with STRICT JSON only, no extra text, in this exact shape:
{"schema_version":"octagon_evals.attribution.v1","status":"candidate",
 "phenomenon":"...",
 "root_causes":[{"category":"agent_behavior|rubric|evidence|workflow|insufficient_evidence",
                 "description":"...","evidence_refs":[],"confidence":"high|medium|low"}],
 "suggestions":[{"target":"agent|rubric|evidence|workflow","action":"...","rationale":"..."}],
 "notes":[]}
"""


def _anchors_block(anchors) -> str:
    if not anchors:
        return "（无）"
    lines = []
    for a in anchors:
        if isinstance(a, dict):
            lines.append(f"- score={a.get('score')} `{a.get('label')}`: {a.get('description', '')}")
        else:
            lines.append(f"- {a}")
    return "\n".join(lines)


def build_user_prompt(dimension, score, evidence_meta: dict[str, Any]) -> str:
    """三段块：被评维度（rubric）/ 分数与 judge 理由 / 行为证据位置。"""
    return (
        "# 被评维度（rubric）\n"
        f"- dimension_id: {dimension.id}\n"
        f"- method: {dimension.method}\n"
        f"- question: {dimension.question or dimension.id}\n"
        f"- score_anchors（扣分点）:\n{_anchors_block(dimension.anchors)}\n\n"
        "# 分数与 judge 理由\n"
        f"- value: {score.value}\n"
        f"- judge_reason: {score.reason or ''}\n"
        f"- source: {score.source}\n"
        f"- judge_lineage: {json.dumps(score.lineage, ensure_ascii=False)}\n\n"
        "# 行为证据\n"
        f"- {evidence_meta.get('location', '证据在工作区文件里')}（用 read/bash 自行检索）"
    )


def parse_attribution(content: str) -> dict:
    """容错解析（fence/前置说明）并校验 schema；非法 → InvalidJudgeOutput。"""
    output = parse_judge_content(content)
    _validate(output)
    return output


def _validate(output: dict) -> None:
    if not isinstance(output, dict):
        raise InvalidJudgeOutput("attribution output must be an object")
    if output.get("schema_version") != ATTRIBUTION_SCHEMA_VERSION:
        raise InvalidJudgeOutput("attribution missing or wrong schema_version")
    if output.get("status") != "candidate":
        raise InvalidJudgeOutput("attribution status must be 'candidate'")
    if not isinstance(output.get("phenomenon"), str) or not output["phenomenon"].strip():
        raise InvalidJudgeOutput("attribution requires a non-empty phenomenon")
    root_causes = output.get("root_causes")
    if not isinstance(root_causes, list):
        raise InvalidJudgeOutput("attribution root_causes must be a list")
    for rc in root_causes:
        if not isinstance(rc, dict) or rc.get("category") not in _ROOT_CATEGORIES:
            raise InvalidJudgeOutput(f"invalid root_cause category: {rc!r}")
        if not isinstance(rc.get("description"), str):
            raise InvalidJudgeOutput("root_cause requires a description")
        if rc.get("confidence") not in _CONFIDENCE_LEVELS:
            raise InvalidJudgeOutput(f"invalid root_cause confidence: {rc.get('confidence')!r}")
    suggestions = output.get("suggestions")
    if not isinstance(suggestions, list):
        raise InvalidJudgeOutput("attribution suggestions must be a list")
    for s in suggestions:
        if not isinstance(s, dict) or s.get("target") not in _SUGGESTION_TARGETS:
            raise InvalidJudgeOutput(f"invalid suggestion target: {s!r}")
        if not isinstance(s.get("action"), str):
            raise InvalidJudgeOutput("suggestion requires an action")
