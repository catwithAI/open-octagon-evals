import json
from octagon_evals.integration import OpenAgentOctagonClient

class Resp:
    status=200
    def __init__(self,p): self.p=p
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self): return json.dumps(self.p).encode()

def test_octagon_client_builds_evaluation_input():
    c=OpenAgentOctagonClient("http://octagon",lambda req: Resp({"ok":True}))
    inp=c.evaluation_input("exp", {"id":"run-1","scenario":{"id":"s"},"task":{"id":"t"},"status":"failed"}, {"id":"attempt-1"})
    assert inp.run_id == "run-1" and inp.upstream_completed is True
    assert inp.history["trajectory_ref"].endswith("wire/trajectory")
