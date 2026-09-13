from octagon_evals.db import SQLiteStore
from octagon_evals.human import HumanTaskStore

def test_human_task_survives_restart(tmp_path):
    path=tmp_path / "human.db"; db=SQLiteStore(path)
    hs=HumanTaskStore(db); hs.create("ht-1","run-1","quality",["shot-1"]); hs.assign("ht-1","reviewer-1")
    first=hs.submit("ht-1","reviewer-1",{"value":.9,"reason":"clear"}); db.close()
    db2=SQLiteStore(path); row=db2.get_human_task("ht-1")
    assert row["state"] == "completed" and row["reviewer_id"] == "reviewer-1"
    assert '0.9' in row["score_json"]
    assert first.value == .9
