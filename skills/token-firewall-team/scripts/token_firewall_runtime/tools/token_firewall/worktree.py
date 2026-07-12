from __future__ import annotations

import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GitWorktreeError(RuntimeError):
    pass


def _git(repo: Path, args: list[str], *, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=text,
        check=False,
    )


def _require(process: subprocess.CompletedProcess[Any], message: str) -> Any:
    if process.returncode != 0:
        stderr = process.stderr.decode() if isinstance(process.stderr, bytes) else process.stderr
        raise GitWorktreeError(f"{message}: {(stderr or '').strip()}")
    return process.stdout


def _safe_ref_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not cleaned:
        raise GitWorktreeError(f"cannot derive a safe branch component from {value!r}")
    return cleaned[:80]


@dataclass(frozen=True)
class WorktreeHandle:
    repo_root: Path
    path: Path
    branch: str
    base_commit: str
    directory_modes: dict[str, int]

    def head_commit(self) -> str:
        process = _git(self.path, ["rev-parse", "HEAD"])
        return str(_require(process, "cannot resolve worktree HEAD")).strip()

    def status_porcelain(self) -> str:
        process = _git(self.path, ["status", "--porcelain", "--untracked-files=all"])
        return str(_require(process, "cannot inspect worktree status"))


class GitWorktreeManager:
    """Create a fully isolated local clone for each task.

    A linked Git worktree keeps its index, refs, and object database inside the
    source repository. That breaks workspace-only sandboxes and would require
    granting the Worker write access to source Git metadata. A no-hardlink
    local clone keeps the complete Git trust boundary inside the task folder.
    """
    def __init__(self, repo_root: Path | str, worktree_root: Path | str):
        self.repo_root = Path(repo_root).resolve()
        self.worktree_root = Path(worktree_root).resolve()

    def preflight(self, base_commit: str) -> str:
        top = _git(self.repo_root, ["rev-parse", "--show-toplevel"])
        resolved_top = Path(str(_require(top, "source repository is not a Git worktree")).strip()).resolve()
        if resolved_top != self.repo_root:
            raise GitWorktreeError(f"repo_root must be the Git top level: {resolved_top}")
        status = str(_require(
            _git(self.repo_root, ["status", "--porcelain", "--untracked-files=all"]),
            "cannot inspect source repository",
        ))
        if status.strip():
            raise GitWorktreeError("source repository must be clean before a Runtime POC run")
        resolved = str(_require(
            _git(self.repo_root, ["rev-parse", "--verify", f"{base_commit}^{{commit}}"]),
            "base commit cannot be resolved",
        )).strip()
        if self.worktree_root == self.repo_root or self.worktree_root.is_relative_to(self.repo_root):
            raise GitWorktreeError("worktree_root must be outside the source repository")
        return resolved

    def create(
        self,
        mission_id: str,
        task_id: str,
        base_commit: str,
        *,
        run_id: str | None = None,
    ) -> WorktreeHandle:
        resolved_base = self.preflight(base_commit)
        mission = _safe_ref_component(mission_id)
        task = _safe_ref_component(task_id)
        run = _safe_ref_component(run_id) if run_id else None
        branch = f"token-firewall/{mission}/{task}" + (f"/{run}" if run else "")
        target = self.worktree_root / (run or mission) / task
        if target.exists():
            raise GitWorktreeError(f"worktree target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(self.repo_root), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        _require(process, "isolated git clone failed")
        checkout = _git(target, ["checkout", "--quiet", "-b", branch, resolved_base])
        _require(checkout, "isolated clone checkout failed")
        modes = _directory_modes(target)
        return WorktreeHandle(self.repo_root, target, branch, resolved_base, modes)


def _directory_modes(root: Path) -> dict[str, int]:
    modes = {".": stat.S_IMODE(root.stat().st_mode)}
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            modes[path.relative_to(root).as_posix()] = stat.S_IMODE(path.stat().st_mode)
    return modes


def validate_directory_modes(handle: WorktreeHandle) -> None:
    current = _directory_modes(handle.path)
    changed = {
        path: {"before": mode, "after": current.get(path)}
        for path, mode in handle.directory_modes.items()
        if current.get(path) != mode
    }
    unsafe_new = {
        path: mode
        for path, mode in current.items()
        if path not in handle.directory_modes and not (mode & stat.S_IWUSR and mode & stat.S_IXUSR)
    }
    if changed or unsafe_new:
        raise GitWorktreeError(
            f"runtime changed directory permissions outside Git evidence: changed={changed}, unsafe_new={unsafe_new}"
        )


def sanitize_runtime_ephemera(handle: WorktreeHandle) -> dict[str, list[str]]:
    """Remove only known, untracked runtime artifacts after the model session ends.

    Unknown untracked paths are deliberately preserved so the clean-worktree gate can
    reject them. Symlinks are unlinked rather than followed.
    """

    validate_directory_modes(handle)
    process = _git(handle.path, ["ls-files", "--others", "--exclude-standard", "-z"], text=False)
    raw = _require(process, "cannot enumerate untracked runtime files")
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    removable: set[Path] = set()
    remaining: list[str] = []
    for relative in paths:
        pure_parts = Path(relative).parts
        target: Path | None = None
        if "__pycache__" in pure_parts:
            index = pure_parts.index("__pycache__")
            target = handle.path.joinpath(*pure_parts[: index + 1])
        elif ".pytest_cache" in pure_parts:
            index = pure_parts.index(".pytest_cache")
            target = handle.path.joinpath(*pure_parts[: index + 1])
        elif Path(relative).name == ".DS_Store" or Path(relative).suffix in {".pyc", ".pyo"}:
            target = handle.path / relative
        if target is None:
            remaining.append(relative)
        else:
            removable.add(target)

    removed: list[str] = []
    for target in sorted(removable, key=lambda item: len(item.parts), reverse=True):
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(handle.path.resolve()):
            raise GitWorktreeError(f"runtime cleanup target escapes worktree: {target}")
        relative = target.relative_to(handle.path).as_posix()
        if target.is_symlink() or target.is_file():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            shutil.rmtree(target)
        removed.append(relative)
    return {"removed": sorted(removed), "remaining": sorted(remaining)}


def inspect_commit_range(handle: WorktreeHandle) -> dict[str, Any]:
    validate_directory_modes(handle)
    head = handle.head_commit()
    if head == handle.base_commit:
        raise GitWorktreeError("worker produced no commit")
    ancestor = _git(handle.path, ["merge-base", "--is-ancestor", handle.base_commit, head])
    if ancestor.returncode != 0:
        raise GitWorktreeError("worker HEAD is not a descendant of the Work Order base commit")
    status = handle.status_porcelain()
    if status.strip():
        raise GitWorktreeError(f"worker left the worktree dirty:\n{status[:4000]}")

    patch_process = _git(
        handle.path,
        ["diff", "--binary", "--no-ext-diff", f"{handle.base_commit}..{head}", "--"],
        text=False,
    )
    patch = _require(patch_process, "cannot calculate worker patch")
    numstat = str(_require(
        _git(handle.path, ["diff", "--numstat", "--no-ext-diff", f"{handle.base_commit}..{head}", "--"]),
        "cannot calculate worker diff stats",
    ))
    name_status = str(_require(
        _git(handle.path, ["diff", "--name-status", "--no-ext-diff", f"{handle.base_commit}..{head}", "--"]),
        "cannot calculate worker file status",
    ))
    status_names = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type-changed",
    }
    statuses: dict[str, str] = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            raise GitWorktreeError(f"cannot parse git name-status line: {line!r}")
        statuses[parts[-1]] = status_names.get(parts[0][0], parts[0][0])

    files: list[dict[str, Any]] = []
    total_lines = 0
    for line in numstat.splitlines():
        additions_raw, deletions_raw, path = line.split("\t", 2)
        additions = 0 if additions_raw == "-" else int(additions_raw)
        deletions = 0 if deletions_raw == "-" else int(deletions_raw)
        files.append(
            {
                "path": path,
                "status": statuses.get(path, "modified"),
                "additions": additions,
                "deletions": deletions,
            }
        )
        total_lines += additions + deletions
    return {
        "base_commit": handle.base_commit,
        "head_commit": head,
        "patch": patch,
        "changed_files": files,
        "diff_lines": total_lines,
    }


def broker_commit_changes(handle: WorktreeHandle, task_id: str) -> str:
    """Create the authoritative commit without granting the model .git write access."""
    status = handle.status_porcelain()
    if not status.strip():
        raise GitWorktreeError("Worker reported CHANGES_READY but produced no filesystem changes")
    add = _git(handle.path, ["add", "--all", "--"])
    _require(add, "Broker cannot stage Worker changes")
    commit = _git(
        handle.path,
        [
            "-c", "user.name=Token Firewall Broker",
            "-c", "user.email=token-firewall@localhost",
            "commit", "--quiet", "-m", f"token-firewall: deliver {_safe_ref_component(task_id)}",
        ],
    )
    _require(commit, "Broker cannot commit Worker changes")
    return handle.head_commit()
