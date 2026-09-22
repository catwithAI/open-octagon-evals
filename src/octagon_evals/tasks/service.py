import time
from ..errors import InvalidStateTransition, StaleSubmission
from ..models import COMPARISON_METHODS, DimensionTask, EvaluationInput, EvalPlan

def create_tasks(inp: EvaluationInput, plan: EvalPlan, store: "TaskStore | None" = None) -> list[DimensionTask]:
    store = store or TaskStore()
    # 比较维度由 experiment 级 ComparisonTask 驱动，不创建 per-run 任务。
    dims = [d for d in plan.dimensions
            if (d.role == "scored" or d.method == "human_required") and d.method not in COMPARISON_METHODS]
    return [store.create(inp, plan, d.id, d.method) for d in dims]

class TaskStore:
    def __init__(self, db=None): self.tasks = {}; self.results = {}; self.db = db
    def create(self, inp, plan, dimension_id, method):
        key = f"{inp.run_id}:{plan.plan_hash}:{dimension_id}"
        if key not in self.tasks: self.tasks[key] = DimensionTask(key, inp.experiment_id, inp.run_id, plan.plan_hash, dimension_id, method)
        if self.db: self.db.create_task(self.tasks[key])
        return self.tasks[key]
    def claim(self, task_id, lease_seconds=300):
        t = self.tasks[task_id]
        if t.state not in ("queued", "retrying") and not (t.state == "claimed" and t.lease_until and t.lease_until < time.time()): raise InvalidStateTransition(t.state)
        t.state, t.attempts, t.lease_until = "claimed", t.attempts + 1, time.time() + lease_seconds
        if self.db: self.db.update_task(t)
        return t
    def complete(self, task_id):
        t = self.tasks[task_id]
        if t.state != "claimed": raise InvalidStateTransition(t.state)
        t.state, t.lease_until = "completed", None
        if self.db: self.db.update_task(t)
    def retry(self, task_id, max_attempts=3):
        t = self.tasks[task_id]
        t.state = "retrying" if t.attempts < max_attempts else "failed"
        if self.db: self.db.update_task(t)
    def cancel(self, task_id):
        self.tasks[task_id].state = "cancelled"
        if self.db: self.db.update_task(self.tasks[task_id])
    def submit(self, task_id, score, resolved=False):
        t = self.tasks[task_id]
        if t.state == "cancelled": raise StaleSubmission(t.state)
        if t.state == "completed": return self.results.get(task_id, score)
        self.results.setdefault(task_id, score)
        if resolved: self.complete(task_id)
        return self.results[task_id]
