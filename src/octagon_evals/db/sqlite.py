from __future__ import annotations
import json, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from ..models import DimensionTask, DimensionScore

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS plans (
  plan_hash TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, version INTEGER NOT NULL,
  scenario_id TEXT, scenario_version TEXT, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL REFERENCES plans(plan_hash), created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id), scenario_json TEXT NOT NULL,
  task_json TEXT NOT NULL, artifact_json TEXT NOT NULL DEFAULT '{}', history_json TEXT NOT NULL DEFAULT '{}',
  producer_json TEXT NOT NULL DEFAULT '{}', upstream_completed INTEGER NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dimension_tasks (
  id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, run_id TEXT NOT NULL,
  plan_hash TEXT NOT NULL REFERENCES plans(plan_hash), dimension_id TEXT NOT NULL,
  method TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  lease_until REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dimension_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES dimension_tasks(id),
  value REAL NOT NULL CHECK(value >= 0 AND value <= 1), source TEXT NOT NULL,
  raw TEXT, reason TEXT, evidence_refs TEXT NOT NULL, lineage TEXT NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0, resolved_policy TEXT NOT NULL DEFAULT 'proposal', created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_resolved_score ON dimension_scores(task_id) WHERE resolved = 1;
CREATE TABLE IF NOT EXISTS human_tasks (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dimension_id TEXT NOT NULL,
  evidence_refs TEXT NOT NULL, reviewer_id TEXT, state TEXT NOT NULL, score_json TEXT, updated_at REAL NOT NULL
);
"""

class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # The repository ships a small SQLite file, so keep upgrades from the
        # original MVP schema non-destructive and additive.
        for name in ("artifact_json", "history_json", "producer_json"):
            try:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback(); raise

    def close(self): self.conn.close()

    def save_plan(self, plan):
        payload = json.dumps({"dimensions": [d.__dict__ for d in plan.dimensions]}, sort_keys=True)
        self.conn.execute("INSERT OR IGNORE INTO plans VALUES (?,?,?,?,?,?,?)", (plan.plan_hash, plan.schema_version, plan.version, plan.scenario_id, str(plan.scenario_version) if plan.scenario_version is not None else None, payload, time.time()))

    def create_task(self, task: DimensionTask) -> DimensionTask:
        now=time.time()
        self.conn.execute("INSERT OR IGNORE INTO dimension_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)", (task.id,task.experiment_id,task.run_id,task.plan_hash,task.dimension_id,task.method,task.state,task.attempts,task.lease_until,now,now))
        return self.get_task(task.id)

    def save_experiment_run(self, experiment_id, plan_hash, evaluation_input):
        now=time.time()
        self.conn.execute("INSERT OR IGNORE INTO experiments VALUES (?,?,?)", (experiment_id, plan_hash, now))
        existing=self.conn.execute("SELECT plan_hash FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if existing["plan_hash"] != plan_hash: raise ValueError("experiment already uses a different plan_hash")
        payload = {
            "scenario_json": json.dumps(evaluation_input.scenario, sort_keys=True),
            "task_json": json.dumps(evaluation_input.task, sort_keys=True),
            "artifact_json": json.dumps(evaluation_input.artifact, sort_keys=True),
            "history_json": json.dumps(evaluation_input.history, sort_keys=True),
            "producer_json": json.dumps(evaluation_input.producer, sort_keys=True),
            "upstream_completed": int(evaluation_input.upstream_completed),
        }
        prior = self.conn.execute(
            "SELECT experiment_id, scenario_json, task_json, artifact_json, history_json, producer_json, upstream_completed FROM runs WHERE id=?",
            (evaluation_input.run_id,),
        ).fetchone()
        if prior is not None:
            if prior["experiment_id"] != experiment_id or any(prior[key] != value for key, value in payload.items()):
                raise ValueError("run_id already exists with different evaluation input")
            return
        self.conn.execute(
            """INSERT OR IGNORE INTO runs
               (id, experiment_id, scenario_json, task_json, artifact_json,
                history_json, producer_json, upstream_completed, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (evaluation_input.run_id, experiment_id, payload["scenario_json"],
             payload["task_json"], payload["artifact_json"],
             payload["history_json"], payload["producer_json"],
             payload["upstream_completed"], now),
        )

    def list_experiments(self): return self.conn.execute("SELECT * FROM experiments ORDER BY created_at").fetchall()
    def get_plan(self, plan_hash):
        row=self.conn.execute("SELECT * FROM plans WHERE plan_hash=?",(plan_hash,)).fetchone()
        if row is None: raise KeyError(plan_hash)
        return row
    def list_runs(self, experiment_id): return self.conn.execute("SELECT * FROM runs WHERE experiment_id=? ORDER BY created_at", (experiment_id,)).fetchall()
    def list_tasks(self, run_id): return self.conn.execute("SELECT * FROM dimension_tasks WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    def list_scores(self, task_id): return self.conn.execute("SELECT * FROM dimension_scores WHERE task_id=? ORDER BY id", (task_id,)).fetchall()

    def get_task(self, task_id):
        row=self.conn.execute("SELECT * FROM dimension_tasks WHERE id=?",(task_id,)).fetchone()
        if row is None: raise KeyError(task_id)
        return DimensionTask(row["id"],row["experiment_id"],row["run_id"],row["plan_hash"],row["dimension_id"],row["method"],row["state"],row["attempts"],row["lease_until"])

    def update_task(self, task: DimensionTask):
        self.conn.execute("UPDATE dimension_tasks SET state=?, attempts=?, lease_until=?, updated_at=? WHERE id=?", (task.state,task.attempts,task.lease_until,time.time(),task.id))

    def save_score(self, score: DimensionScore, resolved=True):
        existing=self.conn.execute("SELECT * FROM dimension_scores WHERE task_id=? AND resolved=1",(score.task_id,)).fetchone()
        if existing: return self.get_score(existing["id"])
        self.conn.execute("INSERT INTO dimension_scores(task_id,value,source,raw,reason,evidence_refs,lineage,resolved,resolved_policy,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (score.task_id,score.value,score.source,json.dumps(score.raw),score.reason,json.dumps(score.evidence_refs),json.dumps(score.lineage),int(resolved),score.resolved_policy,time.time()))
        return score

    def get_score(self, score_id):
        row=self.conn.execute("SELECT * FROM dimension_scores WHERE id=?",(score_id,)).fetchone()
        if row is None: raise KeyError(score_id)
        return DimensionScore(row["task_id"],row["value"],row["source"],json.loads(row["raw"]) if row["raw"] else None,row["reason"],json.loads(row["evidence_refs"]),json.loads(row["lineage"]),resolved_policy=row["resolved_policy"])

    def save_human_task(self, task):
        self.conn.execute("INSERT OR IGNORE INTO human_tasks VALUES (?,?,?,?,?,?,?,?)", (task.id,task.run_id,task.dimension_id,json.dumps(task.evidence_refs),task.reviewer_id,task.state,json.dumps(task.score.__dict__) if task.score else None,time.time()))
        self.conn.execute("UPDATE human_tasks SET reviewer_id=?, state=?, score_json=?, evidence_refs=?, updated_at=? WHERE id=?", (task.reviewer_id,task.state,json.dumps(task.score.__dict__) if task.score else None,json.dumps(task.evidence_refs),time.time(),task.id))
    def get_human_task(self, task_id):
        row=self.conn.execute("SELECT * FROM human_tasks WHERE id=?",(task_id,)).fetchone()
        if row is None: raise KeyError(task_id)
        return row
