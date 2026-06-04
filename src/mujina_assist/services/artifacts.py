from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


DEFAULT_ZIP_PREFIX = "mujina-ros-tui/"


def git_tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [repo_root / line for line in result.stdout.splitlines() if line.strip()]


def create_review_zip(repo_root: Path, output_path: Path | None = None, *, prefix: str = DEFAULT_ZIP_PREFIX) -> Path:
    repo_root = repo_root.resolve()
    output = output_path or repo_root / "mujina-ros-tui-review.zip"
    output = output.resolve()
    modes = _git_file_modes(repo_root)
    normalized_prefix = _normalize_prefix(prefix)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in git_tracked_files(repo_root):
            relative = path.relative_to(repo_root).as_posix()
            if relative.startswith((".state/", "cache/", "logs/", "workspace/")):
                continue
            info = zipfile.ZipInfo(normalized_prefix + relative)
            mode = modes.get(relative, 0o100644)
            info.external_attr = ((mode & 0o777) or 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return output


def create_release_zip(
    repo_root: Path,
    output_path: Path | None = None,
    *,
    ref: str = "HEAD",
    prefix: str = DEFAULT_ZIP_PREFIX,
) -> Path:
    repo_root = repo_root.resolve()
    output = output_path or repo_root / "mujina-ros-tui-release.zip"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized_prefix = _normalize_prefix(prefix)
    result = subprocess.run(
        ["git", "archive", "--format=zip", f"--prefix={normalized_prefix}", "-o", str(output), ref],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git archive failed")
    return output


def _normalize_prefix(prefix: str) -> str:
    value = prefix.strip().replace("\\", "/")
    if not value:
        return ""
    return value if value.endswith("/") else value + "/"


def _git_file_modes(repo_root: Path) -> dict[str, int]:
    result = subprocess.run(
        ["git", "ls-files", "--stage"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files --stage failed")
    modes: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) != 4:
            continue
        try:
            modes[parts[3]] = int(parts[0], 8)
        except ValueError:
            continue
    return modes
