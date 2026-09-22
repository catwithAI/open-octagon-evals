import json
import os
from pathlib import Path

from octagon_evals.judge_service.workspace import (
    _safe_workspace_path,
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


def test_evidence_workspace_writes_explicit_files_with_subdirectories(tmp_path):
    files = {"run-a/final_state": {"ok": True}, "run-b/final_state": {"ok": False}, "readme": "text"}
    workspace = Path(create_evidence_workspace({"run-a": {"ok": True}}, str(tmp_path), files=files))
    try:
        assert json.loads((workspace / "evidence.json").read_text()) == {"run-a": {"ok": True}}
        assert json.loads((workspace / "run-a" / "final_state").read_text()) == {"ok": True}
        assert json.loads((workspace / "run-b" / "final_state").read_text()) == {"ok": False}
        assert (workspace / "readme").read_text() == "text"
    finally:
        cleanup_workspace(str(workspace))


def test_evidence_workspace_path_escape_is_sanitized(tmp_path):
    workspace = str(tmp_path / "ws")
    os.makedirs(workspace)
    root = os.path.realpath(workspace)
    # `..` 段被清洗掉，解析后仍落在工作区内。
    assert _safe_workspace_path(workspace, "../../escape").startswith(root + os.sep)
    # 正常相对路径保留目录层级。
    assert _safe_workspace_path(workspace, "run-a/final_state").endswith(os.path.join("run-a", "final_state"))
