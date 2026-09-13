"""Small AgentEval case package built from the recent Feishu discussion.

The chat itself is evaluator context.  The rule skills score whether a proposed
evaluation plan addresses the concrete concerns raised in the conversation.
"""
from __future__ import annotations

import re

from agenteval import Plan, RuleRouter, RuleSkill, SkillRegistry
from agenteval.protocols import Case, SkillResult


class EvaluationDesignCoverage(RuleSkill):
    skill_id = "evaluation_design_coverage"
    role = "core"
    question = "Does the plan cover the experimental controls required by the discussion?"
    definition_version = "feishu-chat.eval-design-coverage.v1"

    REQUIREMENTS = {
        "frozen_standard": ("固定 rubric/标准", ("固定", "rubric")),
        "agent_identity": ("被测 agent 和模型", ("被测 agent", "模型")),
        "judge_identity": ("judge 模型", ("judge", "模型")),
        "gold_alignment": ("gold 对齐", ("gold", "对齐")),
        "repeatability": ("重复评估", ("重复", "标准差")),
    }

    def evaluate(self, case: Case, output: str) -> SkillResult:
        text = output.lower()
        subscores = {}
        reasons = {}
        for key, (label, tokens) in self.REQUIREMENTS.items():
            ok = all(token.lower() in text for token in tokens)
            subscores[key] = 1.0 if ok else 0.0
            reasons[key] = f"覆盖：{label}" if ok else f"缺少：{label}"
        value = sum(subscores.values()) / len(subscores)
        return SkillResult(self.skill_id, "ok", value, subscores, reasons)


class Actionability(RuleSkill):
    skill_id = "actionability"
    role = "observation"
    question = "Does the plan turn the discussion into executable next steps?"
    definition_version = "feishu-chat.actionability.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        checks = {
            "sample_size": bool(re.search(r"样本|case|20", output, re.I)),
            "threshold": bool(re.search(r"阈值|>\s*0?\.5|二元", output, re.I)),
            "metrics": bool(re.search(r"准确率|accuracy|标准差|方差", output, re.I)),
            "next_step": bool(re.search(r"下一步|先做|比较|报告|记录", output)),
        }
        subscores = {key: 1.0 if ok else 0.0 for key, ok in checks.items()}
        reasons = {key: ("已明确" if ok else "未明确") for key, ok in checks.items()}
        return SkillResult(self.skill_id, "ok", sum(subscores.values()) / len(subscores), subscores, reasons)


def build_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(EvaluationDesignCoverage())
    registry.register(Actionability())
    return registry


def build_router(registry):
    def route(case: Case, catalog):
        return Plan(
            case_id=case.case_id,
            selected_skills=(
                {"skill_id": "evaluation_design_coverage", "role": "core",
                 "reason": "聊天中明确指出评测口径和可比性信息不完整", "parameters": {}},
                {"skill_id": "actionability", "role": "observation",
                 "reason": "聊天要求把 pilot 讨论转成可执行的评测方案", "parameters": {}},
            ),
            skipped_skills=(),
        )
    return RuleRouter(route)


SKILL_WEIGHTS = {"evaluation_design_coverage": 0.8, "actionability": 0.2}
