import json
from pathlib import Path

from octagon_evals.judge_service.workspace import (
    cleanup_workspace,
    create_evidence_workspace,
)


def test_evidence_workspace_preserves_full_payload_and_avoids_filename_collisions(tmp_path):
    evidence = {"a/b": {"value": 1}, "a?b": {"value": 2}}
    workspace = Path(create_evidence_workspace(evidence, str(tmp_path)))
    try:
        assert json.loads((workspace / "evidence.json").read_text()) == evidence
        files = sorted(path.name for path in (workspace / "evidence").iterdir())
        assert files == ["a_b", "a_b_2"]
        values = [json.loads((workspace / "evidence" / name).read_text()) for name in files]
        assert values == [{"value": 1}, {"value": 2}]
    finally:
        cleanup_workspace(str(workspace))

    assert not workspace.exists()
