from octagon_evals.db import SQLiteStore
from octagon_evals.models import DimensionTask, DimensionScore

def test_sqlite_persists_plan_task_and_score(tmp_path):
    db=SQLiteStore(tmp_path / "evals.db")
    task=DimensionTask("task-1","exp","run","sha256:p","completion","deterministic")
    db.conn.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?)", ("sha256:p",1,1,"scene","1","{}",0))
    assert db.create_task(task).id == "task-1"
    db.save_score(DimensionScore("task-1",.75,"deterministic",raw={"passed":True}), True)
    db.close()
    reopened=SQLiteStore(tmp_path / "evals.db")
    assert reopened.get_task("task-1").state == "queued"
    assert reopened.get_score(1).value == .75
