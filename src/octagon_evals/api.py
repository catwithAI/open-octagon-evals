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
from .models import EvaluationInput, EvalPlan, Dimension, DimensionScore, DimensionTask
from .plan.validator import validate_plan
from .scorers.deterministic import default_registry
from .scorers.agent_judge import AgentJudge, AgentJudgeConfig
from .scorers.agent_judge_client import AgentJudgeClient, AgentJudgeClientConfig
from .scorers.jev import JevJudge, SystemOneConfig
from .attribution import AttributionService
from .judge_service.config import JudgeServiceConfig
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

class AttributeRequest(BaseModel):
    evidence: dict[str, Any] = {}

class CompareRequest(BaseModel):
    dimension_id: str
    evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)

class EvaluateRequest(BaseModel):
    """原子式单次评分请求：一个 run 的 evidence + 若干维度，一次返回全部结果。

    与流程式 API（start_run → score_task）的区别：不进 experiment/task 生命周期，
    单次调用评完返回。method 仅支持 LLM-as-judge 方法族
    （deterministic / agent_judge / agent_judge_agentic / jev_judge）；
    human 与 comparison 维度走既有流程式端点。
    """
    evaluation_id: str
    run_id: str
    scenario: dict[str, Any] = Field(default_factory=dict)
    task: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] = Field(default_factory=dict)
    history: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    producer: dict[str, Any] = Field(default_factory=dict)
    dimensions: list[dict[str, Any]] = Field(min_length=1)
    deadline_seconds: float | None = None
    judge_config: dict[str, Any] = Field(default_factory=dict)

class AtomicAttributeRequest(BaseModel):
    """原子式归因请求：维度 + 已有分数 + 证据，一次调用返回候选归因。

    与流程式 ``/tasks/{id}/attribute`` 的区别：不依赖 experiment/task 生命周期。
    流程式端点要经 ``persisted_plan()`` 反查 experiment 行，而 ``/evaluate``
    只落 plan/task、从不写 experiment，故那条路对 ``/evaluate`` 产生的 task
    必然 404。归因本身只需要 (dimension, score, evidence) 三个值，这里直接收。
    """
    attribution_id: str
    dimension: dict[str, Any]
    score: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)

class HumanSubmitRequest(BaseModel):
    reviewer_id: str
    value: float
    reason: str | None = None

def create_app(db_path: str | None = None, *, judge: AgentJudge | None = None,
               agentic_judge=None, jev_judge=None, attribution=None) -> FastAPI:
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
        jev_judge=jev_judge or JevJudge(SystemOneConfig.from_env()),
    )
    attributor = attribution or AttributionService(JudgeServiceConfig.from_env())
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

    @app.post("/evaluate")
    def evaluate_run(request: EvaluateRequest):
        """LLM-as-judge 原子式评分入口（agent-octagon 外部 judge 模式的对接面）。

        兼容性：复用 service 的 deterministic registry / agent judge / jev judge，
        不新建实验、不落 task 持久化（内存构造 DimensionTask），评分语义与流程式
        ``/tasks/{id}/score`` 完全一致。结果带每维 lineage 与累计 usage，供调用方
        补写 judge 版本锚与成本。``judge_config`` 只接受非敏感覆盖
        （model / endpoint / prompt_version / timeout），API key 始终留在 evals 侧
        配置，不过 HTTP。
        """
        unsupported = {d.get("method") for d in request.dimensions} - {
            "deterministic", "agent_judge", "agent_judge_agentic", "jev_judge",
        }
        if unsupported:
            raise HTTPException(
                409,
                f"/evaluate 不支持 method: {sorted(unsupported)}"
                " —— human 与 comparison 维度走流程式 API",
            )
        try:
            plan = EvalPlan(
                1, 1,
                tuple(Dimension(**d) for d in request.dimensions),
                request.scenario.get("id"), request.scenario.get("version"),
            )
            from .plan.hash import plan_hash
            plan = EvalPlan(
                plan.schema_version, plan.version, plan.dimensions,
                plan.scenario_id, plan.scenario_version, plan_hash(plan),
            )
            for dim in plan.dimensions:
                task = DimensionTask(
                    f"{request.evaluation_id}:{dim.id}",
                    request.evaluation_id, request.run_id, plan.plan_hash,
                    dim.id, dim.method,
                )
                service.tasks.tasks[task.id] = task
            # 落 plan + task：score 落库有 FK（dimension_tasks.plan_hash→plans、
            # dimension_scores.task_id→dimension_tasks）。只建 plan/task，不写
            # experiments/runs——/evaluate 是单次评分入口，不建 experiment 生命周期。
            if service.tasks.db is not None:
                service.tasks.db.save_plan(plan)
                for dim in plan.dimensions:
                    service.tasks.db.create_task(
                        service.tasks.tasks[f"{request.evaluation_id}:{dim.id}"]
                    )
            # per-request judge 覆盖：judge_config 缺省时不新建实例（兼容并发），
            # 提供时仅对本次请求构造临时 AgentJudge，覆盖非敏感字段。
            judge = None
            jc = request.judge_config or {}
            if jc and isinstance(service.judge, AgentJudge):
                from dataclasses import replace
                base = service.judge.config
                judge = AgentJudge(replace(
                    base,
                    model=jc.get("model", base.model),
                    endpoint=jc.get("endpoint", base.endpoint),
                    prompt_version=jc.get("prompt_version", base.prompt_version),
                    timeout=jc.get(
                        "timeout",
                        request.deadline_seconds if request.deadline_seconds else base.timeout,
                    ),
                ), opener=service.judge.opener)
            results = []
            for dim in plan.dimensions:
                task = service.tasks.tasks[f"{request.evaluation_id}:{dim.id}"]
                # complete() 要求 claimed 态：与流程式 score_task 一致，评分前认领
                if task.state == "queued":
                    service.tasks.claim(task.id)
                try:
                    if dim.method == "deterministic":
                        score = service.score_deterministic(task, plan, request.evidence)
                    elif dim.method == "agent_judge":
                        score = service.score_agent_judge(task, plan, request.evidence, judge=judge)
                    elif dim.method == "jev_judge":
                        score = service.score_jev_judge(task, plan, request.evidence)
                    else:
                        score = service.score_agent_judge_agentic(task, plan, request.evidence)
                except Exception as exc:
                    # 与 score_task 一致：scorer 失败不留已认领的 task
                    if task.state == "claimed":
                        service.tasks.retry(task.id)
                    raise HTTPException(422, str(exc)) from exc
                results.append({
                    "dimension_id": dim.id,
                    "method": dim.method,
                    "value": score.value,
                    "reason": score.reason,
                    "raw": score.raw,
                    "evidence_refs": score.evidence_refs,
                    "lineage": score.lineage,
                })
            usage = None
            judge_used = judge if judge is not None else service.judge
            if isinstance(judge_used, AgentJudge) and any(judge_used.usage.values()):
                usage = dict(judge_used.usage)
            return {
                "status": "completed",
                "evaluation_id": request.evaluation_id,
                "run_id": request.run_id,
                "results": results,
                "usage": usage,
                "error": None,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/attribute")
    def attribute_atomic(request: AtomicAttributeRequest):
        """原子式归因入口（agent-octagon 外部归因模式的对接面）。

        归因语义与流程式 ``/tasks/{id}/attribute`` 完全一致——同一个
        ``AttributionService``、同一套 prompt 与校验。差别只在分数从哪来：
        这里由调用方直接给出，因为 agent-octagon 的分数落在它自己的库里，
        不在 evals 的 ``dimension_scores`` 表中。

        产物恒为 ``status="candidate"``，供人工复核，调用方不得自动应用。
        """
        try:
            dimension = Dimension(**request.dimension)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"invalid dimension: {exc}") from exc
        payload = request.score
        if "value" not in payload:
            raise HTTPException(422, "score.value is required")
        try:
            score = DimensionScore(
                task_id=request.attribution_id,
                value=payload["value"],
                source=str(payload.get("source") or "external"),
                raw=payload.get("raw"),
                reason=payload.get("reason"),
                evidence_refs=list(payload.get("evidence_refs") or []),
                lineage=dict(payload.get("lineage") or {}),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"invalid score: {exc}") from exc
        try:
            attribution = attributor.attribute(
                dimension=dimension, score=score, evidence=request.evidence
            )
        except InvalidJudgeOutput as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "attribution_id": request.attribution_id,
            "dimension_id": dimension.id,
            "attribution": attribution,
        }

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
        if task.method not in ("deterministic", "agent_judge", "agent_judge_agentic", "jev_judge"):
            raise HTTPException(409, "task requires human review")
        try:
            if task.state == "queued": service.tasks.claim(task_id)
            if task.method == "deterministic":
                score = service.score_deterministic(task, plan, request.evidence)
            elif task.method == "agent_judge":
                score = service.score_agent_judge(task, plan, request.evidence)
            elif task.method == "jev_judge":
                score = service.score_jev_judge(task, plan, request.evidence)
            else:
                score = service.score_agent_judge_agentic(task, plan, request.evidence)
        except Exception as exc:
            # A scorer error must not leave a leased task permanently claimed;
            # the queue can retry it or mark it failed after the retry budget.
            if task.state == "claimed":
                service.tasks.retry(task_id)
            raise HTTPException(422, str(exc)) from exc
        return {"task_id": task_id, "value": score.value, "source": score.source}

    def _resolved_score(task_id):
        score = service.scores.resolved.get(task_id)
        if score is not None:
            return score
        resolved = [r for r in db.list_scores(task_id) if r["resolved"]]
        if resolved:
            return db.get_score(resolved[-1]["id"])
        return None

    def _task_plan_dimension(task):
        plan = plans.get(task.experiment_id) or persisted_plan(task.experiment_id)
        if plan is None:
            return None, None
        return plan, next((d for d in plan.dimensions if d.id == task.dimension_id), None)

    @app.post("/tasks/{task_id}/attribute")
    def attribute_task(task_id: str, request: AttributeRequest):
        task = service.tasks.tasks.get(task_id)
        if task is None:
            try:
                task = db.get_task(task_id)
            except KeyError:
                raise HTTPException(404, "task not found")
        plan, dimension = _task_plan_dimension(task)
        if plan is None or dimension is None:
            raise HTTPException(404, "plan or dimension not found")
        score = _resolved_score(task_id)
        if score is None:
            raise HTTPException(422, "task has no resolved score to attribute")
        try:
            return attributor.attribute(dimension=dimension, score=score, evidence=request.evidence)
        except InvalidJudgeOutput as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/runs/{run_id}/attribute")
    def attribute_run(run_id: str, request: AttributeRequest):
        if not service.tasks.tasks:
            for row in db.list_runs(run_id):
                for task_row in db.list_tasks(row["id"]):
                    service.tasks.tasks[task_row["id"]] = db.get_task(task_row["id"])
        tasks = [t for t in service.tasks.tasks.values() if t.run_id == run_id]
        results = []
        for task in tasks:
            plan, dimension = _task_plan_dimension(task)
            score = _resolved_score(task.id)
            if plan is None or dimension is None or score is None:
                continue
            try:
                attribution = attributor.attribute(dimension=dimension, score=score, evidence=request.evidence)
                results.append({"task_id": task.id, "dimension_id": task.dimension_id, "attribution": attribution})
            except InvalidJudgeOutput as exc:
                results.append({"task_id": task.id, "dimension_id": task.dimension_id, "error": str(exc)})
        if not results:
            raise HTTPException(422, "run has no scored dimensions to attribute")
        return {"run_id": run_id, "attributions": results}

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
