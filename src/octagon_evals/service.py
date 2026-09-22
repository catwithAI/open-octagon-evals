from __future__ import annotations
import json
from dataclasses import replace

from .models import (COMPARISON_METHODS, ComparisonConfig, ComparisonTask,
                     DimensionTask, EvaluationInput, EvalPlan)
from .plan.validator import validate_plan
from .tasks.service import TaskStore, create_tasks
from .scores.service import ScoreStore
from .aggregation import aggregate
from .scorers.runner import ScorerRunner
from .scorers.agent_judge import AgentJudge
from .scorers.jev import JevJudge
from .scorers.pairwise import PairwiseScorer
from .scorers.listwise import ListwiseScorer

class EvaluationService:
    def __init__(self, *, db=None, registry=None, judge: AgentJudge | None = None,
                 agentic_judge=None, jev_judge: JevJudge | None = None):
        self.db=db; self.tasks=TaskStore(db); self.scores=ScoreStore(db)
        self.runner=ScorerRunner(registry) if registry else None
        self.judge=judge
        self.agentic_judge=agentic_judge
        self.jev_judge=jev_judge
        self._comparison_completed: set[str] = set()
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
    def score_jev_judge(self, task, plan, evidence):
        if self.jev_judge is None:
            raise RuntimeError("no jev judge configured")
        dimension = next((d for d in plan.dimensions if d.id == task.dimension_id), None)
        if dimension is None:
            raise ValueError(f"unknown dimension: {task.dimension_id}")
        score = self.jev_judge.score(
            task.id,
            evidence,
            dimension.question or dimension.id,
            anchors=dimension.anchors,
            output_schema=dimension.output_schema,
            evidence_keys=dimension.evidence,
            jev_questions=dimension.jev_questions,
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
    def score_comparison(self, experiment_id: str, plan: EvalPlan, dimension_id: str, evidence_by_run: dict):
        """驱动一个比较维度：对偶/排序 → 裁决 → 持久化原语 → 派生标量。

        返回 {run_id: DimensionScore}。幂等性来自两处：pair/rank 原语按
        task_id 落库，命中即复用不重采样；派生标量按 task_id 幂等记录。
        """
        dimension = next((d for d in plan.dimensions if d.id == dimension_id), None)
        if dimension is None:
            raise ValueError(f"unknown dimension: {dimension_id}")
        if dimension.method not in COMPARISON_METHODS:
            raise ValueError(f"dimension {dimension_id} is not a comparison dimension")
        if not evidence_by_run:
            raise ValueError("comparison requires at least one run of evidence")
        if self.db:
            self.db.save_plan(plan)

        task = ComparisonTask(
            id=f"{experiment_id}:{plan.plan_hash}:{dimension_id}",
            experiment_id=experiment_id,
            plan_hash=plan.plan_hash,
            dimension_id=dimension_id,
            method=dimension.method,
        )
        if task.id in self._comparison_completed:
            return self._derived_scores(dimension_id)
        if self.db:
            self.db.save_comparison_task(task)

        backend = self._comparison_backend(dimension.method)
        config = self._comparison_config(dimension)
        existing = self._existing_verdicts(experiment_id, dimension_id)
        question = dimension.question or dimension.id
        anchors = list(dimension.anchors or ())

        if dimension.method.startswith("pairwise"):
            scorer = PairwiseScorer(backend)
            comparisons, scores = scorer.run(task, dimension, evidence_by_run, config, existing)
            verdict = None
            kind = "pair"
            if self.db:
                for c in comparisons:
                    input_ = {
                        "question": question,
                        "anchors": anchors,
                        # 保留 judge 实际看到的呈现顺序（呈现顺序被种子随机化以缓解位置偏差）。
                        "candidates": [
                            {"id": pid, "evidence": evidence_by_run[pid]}
                            for pid in c["presented"]
                        ],
                    }
                    output = {"winner": c["winner"], "reason": c["reason"], "raw": c["raw"]}
                    self.db.save_comparison(task_id=c["pair_key"], experiment_id=experiment_id,
                                            plan_hash=plan.plan_hash, dimension_id=dimension_id,
                                            kind=kind, input_=input_, output=output,
                                            lineage={"strategy": config.strategy, "allow_ties": config.allow_ties})
        else:
            scorer = ListwiseScorer(backend)
            verdict, scores = scorer.run(task, dimension, evidence_by_run, config, existing)
            comparisons = []
            rank_key = f"{task.id}:rank"
            if self.db:
                input_ = {
                    "question": question,
                    "anchors": anchors,
                    "candidates": [{"id": rid, "evidence": evidence_by_run[rid]} for rid in sorted(evidence_by_run)],
                }
                output = {"ranking": verdict["ranking"], "reason": verdict.get("reason"), "raw": verdict.get("raw")}
                self.db.save_comparison(task_id=rank_key, experiment_id=experiment_id,
                                        plan_hash=plan.plan_hash, dimension_id=dimension_id,
                                        kind="rank", input_=input_, output=output,
                                        lineage={"max_candidates": config.max_candidates})

        derived = self._record_derived(task, dimension, config, scores, comparisons, verdict)
        self._comparison_completed.add(task.id)
        task.state = "completed"
        if self.db:
            self.db.save_comparison_task(task)
        return derived

    def total(self, plan, run_id):
        by_dimension = {self.tasks.tasks[task_id].dimension_id: score for task_id, score in self.scores.resolved.items() if task_id in self.tasks.tasks and self.tasks.tasks[task_id].run_id == run_id}
        return aggregate(plan.dimensions, by_dimension, plan_hash=plan.plan_hash)
    def experiment_totals(self, plan, experiment_id):
        run_ids = sorted({t.run_id for t in self.tasks.tasks.values() if t.experiment_id == experiment_id})
        return {"experiment_id": experiment_id, "plan_hash": plan.plan_hash, "runs": {run_id: self.total(plan, run_id) for run_id in run_ids}}

    # --- comparison helpers -------------------------------------------------

    def _comparison_backend(self, method):
        if method in ("pairwise_judge", "listwise_judge"):
            if self.judge is None:
                raise RuntimeError("no inline judge configured for comparison method")
            return self.judge
        if self.agentic_judge is None:
            raise RuntimeError("no agentic judge configured for comparison method")
        return self.agentic_judge

    def _comparison_config(self, dimension) -> ComparisonConfig:
        config = dimension.comparison or ComparisonConfig()
        if dimension.method.startswith("listwise"):
            config = replace(config, conversion="rank_interpolation")
        return config

    def _existing_verdicts(self, experiment_id, dimension_id) -> dict:
        if not self.db:
            return {}
        return {row["task_id"]: json.loads(row["output_json"])
                for row in self.db.list_comparisons(experiment_id=experiment_id, dimension_id=dimension_id)}

    def _derived_scores(self, dimension_id) -> dict:
        return {self.tasks.tasks[tid].run_id: score
                for tid, score in self.scores.resolved.items()
                if tid in self.tasks.tasks and self.tasks.tasks[tid].dimension_id == dimension_id}

    def _record_derived(self, task: ComparisonTask, dimension, config, scores, comparisons, verdict=None) -> dict:
        derived: dict[str, object] = {}
        judge_calls = len(comparisons) if comparisons else (1 if verdict else 0)
        for run_id, value in scores.items():
            if value is None:
                continue
            d_task = DimensionTask(f"{run_id}:{task.plan_hash}:{dimension.id}",
                                   task.experiment_id, run_id, task.plan_hash,
                                   dimension.id, dimension.method, state="completed")
            self.tasks.tasks[d_task.id] = d_task
            if self.db:
                self.db.create_task(d_task)
            lineage, reason = self._derived_lineage(task, dimension, config, comparisons, verdict, run_id, value)
            score = self.scores.record(
                d_task,
                {"value": value, "raw": {"conversion": config.conversion,
                                         "judge_calls": judge_calls},
                 "reason": reason},
                dimension.method,
                lineage,
            )
            derived[run_id] = score
        return derived

    def _derived_lineage(self, task, dimension, config, comparisons, verdict, run_id, value):
        base = {
            "conversion": config.conversion,
            "conversion_version": config.conversion_version,
            "position_order": "seeded-random",
        }
        if dimension.method.startswith("pairwise"):
            wins = losses = ties = comps = 0
            for c in comparisons:
                if run_id not in (c["a"], c["b"]):
                    continue
                comps += 1
                if c["winner"] == run_id:
                    wins += 1
                elif c["winner"] == "tie":
                    ties += 1
                else:
                    losses += 1
            return {
                **base,
                "comparison_type": "pairwise",
                "strategy": config.strategy,
                "allow_ties": config.allow_ties,
                "comparisons": comps, "wins": wins, "losses": losses, "ties": ties,
                "pair_task_ids": [c["pair_key"] for c in comparisons],
            }, f"{wins}W/{losses}L/{ties}T in {comps} comparisons"
        rank = next((i for i, rid in enumerate(verdict["ranking"]) if rid == run_id), None)
        return {
            **base,
            "comparison_type": "listwise",
            "rank": rank,
            "rank_task_id": f"{task.id}:rank",
        }, f"ranked #{rank + 1} of {len(verdict['ranking'])}" if rank is not None else "unranked"
