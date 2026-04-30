from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mujina_assist.models import AppPaths, RuntimeState
from mujina_assist.services.shell import CommandResult, shell_quote


UPSTREAM_METADATA_SCHEMA_VERSION = 1
VANILLA_MODE = "vanilla"
ASSISTED_MODE = "assisted"
DIAGNOSTIC_MODE = "diagnostic"
WORKSPACE_IGNORED_NAMES = {".git", ".mujina-upstream.json"}
WorkspaceMode = Literal["vanilla", "assisted", "diagnostic"]


@dataclass(slots=True)
class UpstreamMetadata:
    repo_url: str = ""
    upstream_commit: str = ""
    mode: str = ASSISTED_MODE
    patch_set_hash: str = ""
    dirty: bool = False
    workspace_signature: str = ""
    vendored_tree_hash: str = ""
    workspace_tree_hash: str = ""
    applied_patches: list[str] = field(default_factory=list)
    generated_at: str = ""
    schema_version: int = UPSTREAM_METADATA_SCHEMA_VERSION


@dataclass(slots=True)
class WorkspacePreparationResult:
    command: str
    returncode: int
    mode: str
    workspace_signature: str = ""
    upstream_commit: str = ""
    patch_set_hash: str = ""
    applied_patches: list[Path] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def as_command_result(self) -> CommandResult:
        output_lines = [self.stdout.strip()] if self.stdout.strip() else []
        if self.workspace_signature:
            output_lines.append(f"workspace_signature={self.workspace_signature}")
        return CommandResult(
            command=self.command,
            returncode=self.returncode,
            stdout="\n".join(output_lines),
            stderr=self.stderr,
        )

    @property
    def patched(self) -> bool:
        return bool(self.applied_patches)

    @property
    def patch_count(self) -> int:
        return len(self.applied_patches)


def vendored_upstream_path(paths: AppPaths) -> Path:
    return paths.vendored_upstream_dir


def patches_path(paths: AppPaths) -> Path:
    return paths.upstream_patches_dir


def upstream_metadata_path(paths: AppPaths) -> Path:
    return paths.upstream_metadata_file


def read_upstream_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_upstream_metadata(path: Path, metadata: dict[str, Any] | UpstreamMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_data = metadata_to_dict(metadata) if isinstance(metadata, UpstreamMetadata) else dict(metadata)
    payload = json.dumps(payload_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_upstream_metadata(paths: AppPaths) -> UpstreamMetadata:
    return metadata_from_dict(read_upstream_metadata(upstream_metadata_path(paths)))


def save_upstream_metadata(paths: AppPaths, metadata: UpstreamMetadata) -> None:
    write_upstream_metadata(upstream_metadata_path(paths), metadata)


def metadata_from_dict(data: dict[str, Any]) -> UpstreamMetadata:
    metadata = UpstreamMetadata()
    for key, value in data.items():
        if not hasattr(metadata, key):
            continue
        if key in {"dirty"} and isinstance(value, bool):
            setattr(metadata, key, value)
        elif key in {"schema_version"} and isinstance(value, int):
            setattr(metadata, key, value)
        elif key == "applied_patches" and isinstance(value, list):
            metadata.applied_patches = [str(item) for item in value if isinstance(item, str)]
        elif isinstance(value, str):
            setattr(metadata, key, value)
    return metadata


def metadata_to_dict(metadata: UpstreamMetadata) -> dict[str, Any]:
    return {
        "repo_url": metadata.repo_url,
        "upstream_commit": metadata.upstream_commit,
        "mode": metadata.mode,
        "patch_set_hash": metadata.patch_set_hash,
        "dirty": metadata.dirty,
        "workspace_signature": metadata.workspace_signature,
        "vendored_tree_hash": metadata.vendored_tree_hash,
        "workspace_tree_hash": metadata.workspace_tree_hash,
        "applied_patches": list(metadata.applied_patches),
        "generated_at": metadata.generated_at,
        "schema_version": metadata.schema_version,
    }


def vendored_upstream_exists(paths: AppPaths) -> bool:
    return _directory_has_files(paths.vendored_upstream_dir)


def workspace_exists(paths: AppPaths) -> bool:
    return _directory_has_files(paths.upstream_dir)


def patch_set_hash(path_or_paths: Path | AppPaths) -> str:
    patch_dir = path_or_paths.upstream_patches_dir if isinstance(path_or_paths, AppPaths) else path_or_paths
    return _tree_hash(patch_dir, suffixes=(".patch", ".diff"))


def build_workspace_signature(
    *,
    upstream_commit: str,
    patch_set_hash: str,
    dirty: bool,
    mode: str = ASSISTED_MODE,
    workspace_tree_hash: str = "",
) -> str:
    if not upstream_commit and not patch_set_hash and not dirty and not workspace_tree_hash:
        return ""
    suffix = "-dirty" if dirty else "-clean"
    patch_label = patch_set_hash if patch_set_hash else "no-patches"
    commit_label = upstream_commit if upstream_commit else "unknown-upstream"
    mode_label = mode or ASSISTED_MODE
    tree_label = workspace_tree_hash if workspace_tree_hash else "unknown-tree"
    return f"{commit_label}+{mode_label}+patches={patch_label}+tree={tree_label}{suffix}"


def current_workspace_metadata(paths: AppPaths) -> UpstreamMetadata:
    metadata = load_upstream_metadata(paths)
    upstream_commit = metadata.upstream_commit or detect_upstream_commit(paths.upstream_dir)
    patches_hash = metadata.patch_set_hash
    if metadata.mode == ASSISTED_MODE and not patches_hash:
        patches_hash = patch_set_hash(paths)
    dirty = workspace_dirty(paths, metadata=metadata)
    signature = build_workspace_signature(
        upstream_commit=upstream_commit,
        patch_set_hash=patches_hash if metadata.mode == ASSISTED_MODE else "",
        dirty=dirty,
        mode=metadata.mode or ASSISTED_MODE,
        workspace_tree_hash=metadata.workspace_tree_hash,
    )
    metadata.upstream_commit = upstream_commit
    metadata.patch_set_hash = patches_hash
    metadata.dirty = dirty
    metadata.workspace_signature = signature
    return metadata


def workspace_signature(paths: AppPaths) -> str:
    return current_workspace_metadata(paths).workspace_signature


def workspace_dirty(paths: AppPaths, *, metadata: UpstreamMetadata | None = None) -> bool:
    if not paths.upstream_dir.exists():
        return False
    git_dirty = _git_dirty(paths.upstream_dir)
    if git_dirty is not None:
        return git_dirty
    metadata = metadata or load_upstream_metadata(paths)
    if not metadata.workspace_tree_hash:
        return False
    return _tree_hash(paths.upstream_dir, ignored_names=WORKSPACE_IGNORED_NAMES) != metadata.workspace_tree_hash


def detect_upstream_commit(path: Path) -> str:
    commit = _git_stdout(path, ["rev-parse", "HEAD"])
    if commit:
        return commit
    metadata_file = path / ".mujina-upstream.json"
    data = read_upstream_metadata(metadata_file)
    commit_value = data.get("upstream_commit", "")
    return commit_value if isinstance(commit_value, str) else ""


def prepare_workspace(
    paths: AppPaths,
    *,
    mode: WorkspaceMode = ASSISTED_MODE,
    replace: bool = True,
    repo_url: str = "",
) -> WorkspacePreparationResult:
    command = f"prepare vendored mujina_ros ({mode})"
    if mode not in {VANILLA_MODE, ASSISTED_MODE, DIAGNOSTIC_MODE}:
        return WorkspacePreparationResult(command, 2, mode, stderr=f"unknown workspace mode: {mode}")
    if not vendored_upstream_exists(paths):
        return WorkspacePreparationResult(
            command,
            1,
            mode,
            stderr=f"vendored upstream is missing: {paths.vendored_upstream_dir}",
        )
    if paths.upstream_dir.exists() and not replace:
        metadata = current_workspace_metadata(paths)
        return WorkspacePreparationResult(
            command,
            0,
            metadata.mode,
            workspace_signature=metadata.workspace_signature,
            upstream_commit=metadata.upstream_commit,
            patch_set_hash=metadata.patch_set_hash,
            stdout="workspace already exists",
        )

    tmp_dir = paths.upstream_dir.with_name(f"{paths.upstream_dir.name}.tmp-{os.getpid()}")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    applied_patches: list[Path] = []
    try:
        shutil.copytree(paths.vendored_upstream_dir, tmp_dir, ignore=shutil.ignore_patterns(".git"))
        if mode == ASSISTED_MODE:
            applied_patches = apply_patch_queue(tmp_dir, paths.upstream_patches_dir)
        upstream_commit = detect_upstream_commit(paths.vendored_upstream_dir)
        patches_hash = patch_set_hash(paths) if mode == ASSISTED_MODE else ""
        workspace_tree_hash = _tree_hash(tmp_dir, ignored_names=WORKSPACE_IGNORED_NAMES)
        signature = build_workspace_signature(
            upstream_commit=upstream_commit,
            patch_set_hash=patches_hash,
            dirty=False,
            mode=mode,
            workspace_tree_hash=workspace_tree_hash,
        )
        metadata = UpstreamMetadata(
            repo_url=repo_url,
            upstream_commit=upstream_commit,
            mode=mode,
            patch_set_hash=patches_hash,
            dirty=False,
            workspace_signature=signature,
            vendored_tree_hash=_tree_hash(paths.vendored_upstream_dir, ignored_names={".git"}),
            workspace_tree_hash=workspace_tree_hash,
            applied_patches=[path.relative_to(paths.upstream_patches_dir).as_posix() for path in applied_patches],
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        write_upstream_metadata(tmp_dir / ".mujina-upstream.json", metadata)
        if paths.upstream_dir.exists():
            shutil.rmtree(paths.upstream_dir)
        paths.upstream_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_dir, paths.upstream_dir)
        save_upstream_metadata(paths, metadata)
        return WorkspacePreparationResult(
            command,
            0,
            mode,
            workspace_signature=signature,
            upstream_commit=upstream_commit,
            patch_set_hash=patches_hash,
            applied_patches=applied_patches,
            stdout=_prepare_workspace_stdout(paths.vendored_upstream_dir, mode, applied_patches),
        )
    except Exception as exc:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return WorkspacePreparationResult(command, 1, mode, stderr=str(exc))


def prepare_workspace_from_vendored_upstream(
    paths: AppPaths,
    *,
    mode: WorkspaceMode = ASSISTED_MODE,
    replace: bool = True,
) -> WorkspacePreparationResult:
    return prepare_workspace(paths, mode=mode, replace=replace)


def copy_vendored_upstream_to_workspace(paths: AppPaths, *, replace: bool = False) -> bool:
    return prepare_workspace(paths, mode=VANILLA_MODE, replace=replace).returncode == 0


def apply_upstream_patches(paths: AppPaths) -> list[Path]:
    return apply_patch_queue(paths.upstream_dir, paths.upstream_patches_dir)


def _prepare_workspace_stdout(vendored_dir: Path, mode: str, applied_patches: list[Path]) -> str:
    lines = [f"prepared workspace from {vendored_dir}"]
    if mode == ASSISTED_MODE and not applied_patches:
        lines.append("warning: assisted mode selected but patch queue is empty")
    return "\n".join(lines)


def apply_patch_queue(workspace_dir: Path, patch_dir: Path) -> list[Path]:
    patch_files = _patch_files(patch_dir)
    if not patch_files:
        return []
    if not workspace_dir.exists():
        raise FileNotFoundError(workspace_dir)
    for patch_file in patch_files:
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_file)],
            cwd=workspace_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"failed to apply upstream patch {patch_file}: {output}")
    return patch_files


def sync_runtime_workspace_state(paths: AppPaths, state: RuntimeState) -> None:
    metadata = current_workspace_metadata(paths)
    old_signature = state.last_sim_verified_workspace_signature
    state.workspace_mode = metadata.mode
    state.workspace_upstream_commit = metadata.upstream_commit
    state.workspace_patch_set_hash = metadata.patch_set_hash
    state.workspace_dirty = metadata.dirty
    state.workspace_signature = metadata.workspace_signature
    if old_signature and metadata.workspace_signature and old_signature != metadata.workspace_signature:
        state.last_sim_success = False
        state.last_sim_verified_at = ""
        state.last_sim_verified_label = ""
        state.last_sim_verified_source = ""
        state.last_sim_verified_workspace_signature = ""


def append_log_line(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def prepare_workspace_command_result(
    paths: AppPaths,
    log_path: Path,
    *,
    mode: WorkspaceMode = ASSISTED_MODE,
    replace: bool = True,
    repo_url: str = "",
) -> CommandResult:
    result = prepare_workspace(paths, mode=mode, replace=replace, repo_url=repo_url)
    append_log_line(log_path, f"$ {result.command}")
    if result.stdout:
        append_log_line(log_path, result.stdout)
    if result.stderr:
        append_log_line(log_path, result.stderr)
    if result.applied_patches:
        append_log_line(log_path, "applied patches:")
        for patch_file in result.applied_patches:
            append_log_line(log_path, f"  - {patch_file}")
    return result.as_command_result()


def clone_to_vendored_command(repo_url: str, paths: AppPaths) -> str:
    quoted_repo = shell_quote(repo_url)
    quoted_target = shell_quote(paths.vendored_upstream_dir)
    return f"git clone {quoted_repo} {quoted_target}"


def _directory_has_files(root: Path) -> bool:
    if not root.is_dir():
        return False
    return any(path.is_file() for path in root.rglob("*"))


def _patch_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".patch", ".diff"}),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _tree_hash(
    root: Path,
    *,
    suffixes: tuple[str, ...] | None = None,
    ignored_names: set[str] | None = None,
) -> str:
    if not root.is_dir():
        return ""
    ignored = ignored_names or set()
    files: list[Path] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part in ignored for part in relative_parts):
            continue
        if not path.is_file():
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        files.append(path)
    if not files:
        return ""

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _git_stdout(path: Path, args: list[str]) -> str:
    if not (path / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _git_dirty(path: Path) -> bool | None:
    if not (path / ".git").exists():
        return None
    status = _git_stdout(path, ["status", "--porcelain"])
    return bool(status)
