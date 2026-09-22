from __future__ import annotations
import json
import os
import shutil
import tempfile
from typing import Any


def create_evidence_workspace(evidence: dict[str, Any], base_dir: str | None = None, files: dict[str, Any] | None = None) -> str:
    """Write the evidence dict into a fresh temp dir the judge agent can explore.

    The full dict is dumped to ``evidence.json``. Without ``files``, each
    top-level key is also written as its own file under ``evidence/`` so pi can
    ``ls``, read, or grep with its tools rather than being handed everything in
    the prompt. With ``files``, each ``path -> content`` pair is written instead
    (paths may contain ``/`` to create subdirectories, e.g. ``run-a/final_state``),
    which lets comparison judges explore each candidate separately.
    """
    workspace = tempfile.mkdtemp(prefix="octagon-judge-", dir=base_dir)
    with open(os.path.join(workspace, "evidence.json"), "w") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    if files is not None:
        for path, value in files.items():
            _write_value(_safe_workspace_path(workspace, path), value)
        return workspace
    evidence_dir = os.path.join(workspace, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    used_names: set[str] = set()
    for key, value in evidence.items():
        base_name = _safe_filename(key)
        filename = base_name
        suffix = 2
        while filename in used_names:
            filename = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(filename)
        _write_value(os.path.join(evidence_dir, filename), value)
    return workspace


def _write_value(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        if isinstance(value, (dict, list)):
            json.dump(value, f, indent=2, ensure_ascii=False)
        else:
            f.write(str(value))


def _safe_workspace_path(workspace: str, path: str) -> str:
    """把 files 的 path 清洗为工作区内的安全相对路径。

    path 按 ``/`` 分段，每段用与默认布局相同的文件名清洗规则，拒绝 ``..``，
    防止 ``../../`` 类路径把文件写到工作区之外（可信环境下的纵深防御）。
    """
    root = os.path.realpath(workspace)
    segments = [s for s in path.replace("\\", "/").split("/") if s and s not in (".", "..")]
    target = os.path.realpath(os.path.join(root, *segments))
    if not target.startswith(root + os.sep) and target != root:
        raise ValueError("workspace file path escapes the workspace")
    return target


def cleanup_workspace(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _safe_filename(key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return safe[:100] or "item"
