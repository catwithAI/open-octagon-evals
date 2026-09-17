from __future__ import annotations
from .models import EvaluationInput, EvalPlan
from .plan.validator import validate_plan
from .tasks.service import TaskStore, create_tasks
from .scores.service import ScoreStore
from .aggregation import aggregate
from .scorers.runner import ScorerRunner
from .scorers.agent_judge import AgentJudge

class EvaluationService:
    def __init__(self, *, db=None, registry=None, judge: AgentJudge | None = None,
                 agentic_judge=None):
        self.db=db; self.tasks=TaskStore(db); self.scores=ScoreStore(db)
        self.runner=ScorerRunner(registry) if registry else None
        self.judge=judge
        self.agentic_judge=agentic_judge
    def start(self, evaluation_input: EvaluationInput, plan: EvalPlan):
        validate_plan(plan)
        from .plan.hash import plan_hash
        if not plan.plan_hash:
            plan = EvalPlan(plan.schema_version, plan.version, plan.dimensions, plan.scenario_id, plan.scenario_version, plan_hash(plan))
        if self.db: self.db.save_plan(plan)
        if self.db: self.db.save_experiment_run(evaluation_input.experiment_id, plan.plan_hash, evaluation_input)
        return create_tasks(evaluation_input, plan, self.tasks)
    def score_deterministic(self, task, plan, evidence):
        if not self.runner: raise RuntimeError("no scorer registry configured")
        task_obj=self.tasks.tasks.get(task.id, task)
        score=self.runner.run(task_obj, evidence, lineage={"plan_hash": plan.plan_hash})
        self.scores.record(task_obj, {"value":score.value,"raw":score.raw,"reason":score.reason,"evidence_refs":score.evidence_refs}, score.source, score.lineage)
        self.tasks.complete(task.id)
        return score
    def score_agent_judge(self, task, plan, evidence):
        if self.judge is None:
            raise RuntimeError("no agent judge configured")
        dimension = next((d for d in plan.dimensions if d.id == task.dimension_id), None)
        if dimension is None:
            raise ValueError(f"unknown dimension: {task.dimension_id}")
        score = self.judge.score(
            task.id,
            evidence,
            dimension.question or dimension.id,
            anchors=dimension.anchors,
            output_schema=dimension.output_schema,
        )
        self.scores.record(
            task,
            {"value": score.value, "raw": score.raw, "reason": score.reason,
             "evidence_refs": score.evidence_refs},
            score.source,
            score.lineage,
        )
        self.tasks.complete(task.id)
        return score
    def score_agent_judge_agentic(self, task, plan, evidence):
        if self.agentic_judge is None:
            raise RuntimeError("no agentic judge configured")
        dimension = next((d for d in plan.dimensions if d.id == task.dimension_id), None)
        if dimension is None:
            raise ValueError(f"unknown dimension: {task.dimension_id}")
        score = self.agentic_judge.score(
            task.id,
            evidence,
            dimension.question or dimension.id,
            anchors=dimension.anchors,
            output_schema=dimension.output_schema,
        )
        self.scores.record(
            task,
            {"value": score.value, "raw": score.raw, "reason": score.reason,
             "evidence_refs": score.evidence_refs},
            score.source,
            score.lineage,
        )
        self.tasks.complete(task.id)
        return score
    def total(self, plan, run_id):
        by_dimension = {self.tasks.tasks[task_id].dimension_id: score for task_id, score in self.scores.resolved.items() if task_id in self.tasks.tasks and self.tasks.tasks[task_id].run_id == run_id}
        return aggregate(plan.dimensions, by_dimension, plan_hash=plan.plan_hash)
    def experiment_totals(self, plan, experiment_id):
        run_ids = sorted({t.run_id for t in self.tasks.tasks.values() if t.experiment_id == experiment_id})
        return {"experiment_id": experiment_id, "plan_hash": plan.plan_hash, "runs": {run_id: self.total(plan, run_id) for run_id in run_ids}}
