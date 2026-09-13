from pathlib import Path
import pytest
from octagon_evals.db import SQLiteStore
from octagon_evals.models import EvaluationInput
from octagon_evals.plan import load_plan
from octagon_evals.scorers.deterministic import default_registry
from octagon_evals.service import EvaluationService
from octagon_evals.worker import DeterministicWorker

def test_documented_frontend_vfx_plan_runs(tmp_path):
    fixture=Path(__file__).parents[1] / "fixtures/plans/frontend-vfx-volcano.yaml"
    plan=load_plan(fixture, capabilities=default_registry().capabilities())
    inp=EvaluationInput("exp-doc","run-doc",{"id":"frontend-vfx-volcano","version":1},{"id":"task-042"},{"snapshot_ref":"snapshot://run-doc","content_hash":"sha256:artifact"},{"trajectory_ref":"history://run-doc"},True)
    db=SQLiteStore(tmp_path/"documented.db"); service=EvaluationService(db=db, registry=default_registry()); tasks=service.start(inp,plan)
    evidence={tasks[0].id:{"checks":[True]}, tasks[1].id:{"requirements":[True,False]}, tasks[2].id:{"dangerous_actions":[]}}
    assert len(DeterministicWorker(service,plan,evidence).run_once()) == 3
    assert service.total(plan, "run-doc")["total_score"] == pytest.approx(.8)
