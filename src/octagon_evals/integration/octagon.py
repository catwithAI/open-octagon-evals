from __future__ import annotations
import json
from dataclasses import dataclass
from urllib.request import Request, urlopen
from ..models import EvaluationInput

@dataclass
class OpenAgentOctagonClient:
    base_url: str = "http://127.0.0.1:8100"
    opener: object = urlopen
    def get(self, path):
        req=Request(self.base_url.rstrip("/")+path, headers={"Accept":"application/json"})
        with self.opener(req) as response:
            if getattr(response, "status", 200) >= 400: raise RuntimeError(f"Octagon request failed: {response.status}")
            return json.loads(response.read())
    def list_experiments(self): return self.get("/api/experiments")
    def get_experiment(self, experiment_id): return self.get(f"/api/experiments/{experiment_id}")
    def list_runs(self, **params):
        query="" if not params else "?"+"&".join(f"{k}={v}" for k,v in params.items())
        return self.get("/api/runs"+query)
    def get_run(self, run_id): return self.get(f"/api/runs/{run_id}")
    def get_attempt(self, run_id, attempt_id): return self.get(f"/api/runs/{run_id}/attempts/{attempt_id}")
    def evaluation_input(self, experiment_id, run: dict, attempt: dict) -> EvaluationInput:
        run_id=run.get("id") or run.get("run_id")
        artifact=attempt.get("artifact") or {"snapshot_ref":f"/api/runs/{run_id}/attempts/{attempt.get('id','')}/artifacts","content_hash":attempt.get("artifact_hash","unknown")}
        history=attempt.get("history") or {"trajectory_ref":f"/api/runs/{run_id}/attempts/{attempt.get('id','')}/wire/trajectory","trace_ref":f"/api/runs/{run_id}/attempts/{attempt.get('id','')}/trace"}
        return EvaluationInput(experiment_id, run_id, run.get("scenario",{}), run.get("task",{}), artifact, history, bool(run.get("status") in ("completed","succeeded","failed","error") or run.get("upstream_completed")))
