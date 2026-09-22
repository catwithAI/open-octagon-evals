from __future__ import annotations
import os
import json
import statistics
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .db import SQLiteStore
from .errors import InvalidJudgeOutput
from .models import EvaluationInput, EvalPlan, Dimension
from .plan.validator import validate_plan
from .scorers.deterministic import default_registry
from .scorers.agent_judge import AgentJudge, AgentJudgeConfig
from .scorers.agent_judge_client import AgentJudgeClient, AgentJudgeClientConfig
from .service import EvaluationService
from .human import HumanTaskStore

class StartRequest(BaseModel):
    run_id: str
    scenario: dict[str, Any]
    task: dict[str, Any]
    artifact: dict[str, Any]
    history: dict[str, Any]
    producer: dict[str, Any] = Field(default_factory=dict)
    upstream_completed: bool = True
    dimensions: list[dict[str, Any]] = Field(min_length=1)
    plan_version: int = 1

class ScoreRequest(BaseModel):
    evidence: dict[str, Any] = {}

class CompareRequest(BaseModel):
    dimension_id: str
    evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)

class HumanSubmitRequest(BaseModel):
    reviewer_id: str
    value: float
    reason: str | None = None

def create_app(db_path: str | None = None, *, judge: AgentJudge | None = None,
               agentic_judge=None) -> FastAPI:
    app = FastAPI(title="octagon-evals", version="0.1.0")
    # The bundled static console is commonly served from a different local
    # port than the API (for example 5180 -> 8030).  Without CORS the browser
    # turns a perfectly healthy API response into a silent empty state because
    # the console intentionally treats fetch failures as no data.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    db = SQLiteStore(db_path or os.getenv("OCTAGON_EVALS_DB", ":memory:"))
    service = EvaluationService(
        db=db,
        registry=default_registry(),
        judge=judge or AgentJudge(AgentJudgeConfig.from_env()),
        agentic_judge=agentic_judge or AgentJudgeClient(AgentJudgeClientConfig.from_env()),
    )
    human = HumanTaskStore(db)
    plans: dict[str, EvalPlan] = {}
    runs: dict[str, str] = {}

    def persisted_plan(experiment_id):
        row = next((r for r in db.list_experiments() if r["id"] == experiment_id), None)
        if not row: return None
        p = db.get_plan(row["plan_hash"]); payload=json.loads(p["payload"])
        return EvalPlan(p["schema_version"], p["version"], tuple(Dimension(**d) for d in payload["dimensions"]), p["scenario_id"], p["scenario_version"], p["plan_hash"])

    @app.post("/experiments/{experiment_id}/runs", status_code=201)
    def start_run(experiment_id: str, request: StartRequest):
        try:
            plan = EvalPlan(1, request.plan_version, tuple(Dimension(**d) for d in request.dimensions), request.scenario.get("id"), request.scenario.get("version"))
            # API callers may omit hash; plans are normalized and hashed before persistence.
            from .plan.hash import plan_hash
            plan = EvalPlan(plan.schema_version, plan.version, plan.dimensions, plan.scenario_id, plan.scenario_version, plan_hash(plan))
            evaluation_input = EvaluationInput(experiment_id, request.run_id, request.scenario, request.task, request.artifact, request.history, request.upstream_completed, request.producer)
            existing = plans.get(experiment_id)
            if existing is not None and existing.plan_hash != plan.plan_hash:
                raise HTTPException(409, "plan_hash mismatch: all runs of an experiment share the frozen EvalPlan")
            tasks = service.start(evaluation_input, plan); plans[experiment_id] = plan; runs[request.run_id] = experiment_id
            return {"experiment_id": experiment_id, "run_id": request.run_id, "plan_hash": plan.plan_hash, "task_ids": [t.id for t in tasks]}
        except (ValueError, KeyError) as exc: raise HTTPException(422, str(exc)) from exc

    @app.post("/tasks/{task_id}/score")
    def score_task(task_id: str, request: ScoreRequest):
        task = service.tasks.tasks.get(task_id)
        if task is None:
            try:
                task = db.get_task(task_id)
                service.tasks.tasks[task_id] = task
            except KeyError:
                raise HTTPException(404, "task not found")
        plan = plans.get(task.experiment_id) or persisted_plan(task.experiment_id)
        if plan is None: raise HTTPException(404, "plan not found")
        if task.method not in ("deterministic", "agent_judge", "agent_judge_agentic"):
            raise HTTPException(409, "task requires human review")
        try:
            if task.state == "queued": service.tasks.claim(task_id)
            if task.method == "deterministic":
                score = service.score_deterministic(task, plan, request.evidence)
            elif task.method == "agent_judge":
                score = service.score_agent_judge(task, plan, request.evidence)
            else:
                score = service.score_agent_judge_agentic(task, plan, request.evidence)
        except Exception as exc:
            # A scorer error must not leave a leased task permanently claimed;
            # the queue can retry it or mark it failed after the retry budget.
            if task.state == "claimed":
                service.tasks.retry(task_id)
            raise HTTPException(422, str(exc)) from exc
        return {"task_id": task_id, "value": score.value, "source": score.source}

    @app.post("/experiments/{experiment_id}/compare")
    def compare_dimension(experiment_id: str, request: CompareRequest):
        plan = plans.get(experiment_id) or persisted_plan(experiment_id)
        if plan is None: raise HTTPException(404, "experiment not found")
        try:
            derived = service.score_comparison(experiment_id, plan, request.dimension_id, request.evidence)
        except (ValueError, KeyError, InvalidJudgeOutput) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "experiment_id": experiment_id,
            "dimension_id": request.dimension_id,
            "scores": {run_id: {"value": s.value, "source": s.source} for run_id, s in derived.items()},
        }

    @app.get("/experiments/{experiment_id}/score")
    def experiment_score(experiment_id: str):
        plan = plans.get(experiment_id)
        if plan is None: plan = persisted_plan(experiment_id)
        if plan is None: raise HTTPException(404, "experiment not found")
        if not service.tasks.tasks:
            for run in db.list_runs(experiment_id):
                for row in db.list_tasks(run["id"]): service.tasks.tasks[row["id"]]=db.get_task(row["id"])
                for task in db.list_tasks(run["id"]):
                    resolved=[r for r in db.list_scores(task["id"]) if r["resolved"]]
                    if resolved: service.scores.resolved[task["id"]]=db.get_score(resolved[-1]["id"])
        return service.experiment_totals(plan, experiment_id)

    @app.get("/experiments/{experiment_id}")
    def experiment_detail(experiment_id: str):
        plan=plans.get(experiment_id) or persisted_plan(experiment_id)
        if plan is None: raise HTTPException(404,"experiment not found")
        runs=[]
        for run in db.list_runs(experiment_id):
            dimensions=[]
            for task_row in db.list_tasks(run["id"]):
                task_id=task_row["id"]; rows=db.list_scores(task_id)
                resolved=next((dict(r) for r in reversed(rows) if r["resolved"]), None)
                values=[r["value"] for r in rows]; stability={"count":len(values),"mean":statistics.mean(values) if values else None,"stdev":statistics.pstdev(values) if len(values)>1 else 0.0,"range":(max(values)-min(values)) if values else None}
                dimensions.append({"dimension_id":task_row["dimension_id"],"method":task_row["method"],"state":task_row["state"],"attempts":task_row["attempts"],"score":resolved["value"] if resolved else None,"proposal_count":len(rows),"stability":stability})
            try:
                producer = json.loads(run["producer_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                producer = {}
            runs.append({"run_id":run["id"],"producer":producer,"dimensions":dimensions})
        return {"experiment_id":experiment_id,"plan_hash":plan.plan_hash,"plan_version":plan.version,"dimensions":[{"id":d.id,"role":d.role,"weight":d.weight,"method":d.method,"version":d.version} for d in plan.dimensions],"runs":runs}

    @app.get("/experiments")
    def list_experiments():
        result = []
        for row in db.list_experiments():
            runs = db.list_runs(row["id"])
            tasks = [task for run in runs for task in db.list_tasks(run["id"])]
            resolved = sum(bool(db.list_scores(task["id"])) and any(s["resolved"] for s in db.list_scores(task["id"])) for task in tasks)
            result.append({
                "experiment_id": row["id"], "run_count": len(runs),
                "plan_hash": row["plan_hash"], "created_at": row["created_at"],
                "task_count": len(tasks), "resolved_count": resolved,
                "status": "final" if tasks and resolved == len(tasks) else "pending",
            })
        return result

    @app.get("/tasks/{task_id}")
    def task_detail(task_id: str):
        task=service.tasks.tasks.get(task_id)
        if task is None:
            try: task=db.get_task(task_id)
            except KeyError: raise HTTPException(404,"task not found")
        return {"task_id":task_id,"state":task.state if hasattr(task,"state") else task["state"],"attempts":task.attempts if hasattr(task,"attempts") else task["attempts"],"scores":[dict(r) for r in db.list_scores(task_id)]}

    @app.post("/human-tasks/{task_id}", status_code=201)
    def create_human_task(task_id: str):
        task=service.tasks.tasks.get(task_id)
        if task is None:
            try:
                task = db.get_task(task_id)
                service.tasks.tasks[task_id] = task
            except KeyError:
                raise HTTPException(404,"task not found")
        if task.method != "human_required": raise HTTPException(409,"task does not require human review")
        plan = plans.get(task.experiment_id) or persisted_plan(task.experiment_id)
        dimension = next((d for d in (plan.dimensions if plan else ()) if d.id == task.dimension_id), None)
        return human.create(task_id, task.run_id, task.dimension_id, dimension.evidence if dimension else ()).__dict__

    @app.post("/human-tasks/{task_id}/assign")
    def assign_human_task(task_id: str, reviewer_id: str):
        try: return human.assign(task_id, reviewer_id).__dict__
        except KeyError: raise HTTPException(404,"human task not found")

    @app.post("/human-tasks/{task_id}/submit")
    def submit_human_task(task_id: str, request: HumanSubmitRequest):
        try: score=human.submit(task_id, request.reviewer_id, {"value":request.value,"reason":request.reason})
        except KeyError: raise HTTPException(404,"human task not found")
        except Exception as exc: raise HTTPException(409,str(exc)) from exc
        task = service.tasks.tasks.get(task_id)
        if task is None:
            try:
                task = db.get_task(task_id)
                service.tasks.tasks[task_id] = task
            except KeyError:
                raise HTTPException(404, "task not found")
        if task is not None and task.state != "completed":
            if task.state == "queued": service.tasks.claim(task_id)
            service.scores.record(task, {"value":score.value,"raw":score.raw,"reason":score.reason}, "human", score.lineage)
            service.tasks.complete(task_id)
        return {"task_id":task_id,"value":score.value,"source":"human"}

    @app.post("/human-tasks/{task_id}/expire")
    def expire_human_task(task_id: str):
        try: human.expire(task_id); return {"task_id":task_id,"state":human.tasks[task_id].state}
        except KeyError: raise HTTPException(404,"human task not found")

    return app

app = create_app()
