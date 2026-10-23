"""Canonical filesystem locations for the Harvey checkout and active workspace.

Harvey supports both repo-root execution and multi-product workspaces.
Source code & engine live in PROJECT_ROOT.
Product-specific config (harvey.yaml, .env), knowledge (skills/),
and state (data/, leads) live in the active WORKSPACE_DIR.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ACTIVE_WORKSPACE_OVERRIDE: Path | None = None


def set_workspace_dir(ws: str | Path | None) -> Path:
    """Explicitly set the active workspace directory for this process."""
    global _ACTIVE_WORKSPACE_OVERRIDE
    if ws is None:
        _ACTIVE_WORKSPACE_OVERRIDE = None
        return get_workspace_dir()

    p = Path(ws)
    if not p.is_absolute():
        if (Path.cwd() / p).exists():
            resolved = (Path.cwd() / p).resolve()
        elif (PROJECT_ROOT / "workspaces" / p).exists():
            resolved = (PROJECT_ROOT / "workspaces" / p).resolve()
        else:
            resolved = (PROJECT_ROOT / p).resolve()
    else:
        resolved = p.resolve()

    _ACTIVE_WORKSPACE_OVERRIDE = resolved
    os.environ["HARVEY_WORKSPACE"] = str(resolved)
    return resolved


def get_workspace_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the active workspace directory.

    Resolution order:
    1. Explicit parameter if provided
    2. In-memory override set via set_workspace_dir()
    3. HARVEY_WORKSPACE environment variable (name or path)
    4. Current working directory if it contains harvey.yaml or harvey.local.yaml
    5. Fallback: PROJECT_ROOT
    """
    if explicit:
        return set_workspace_dir(explicit)

    if _ACTIVE_WORKSPACE_OVERRIDE is not None:
        return _ACTIVE_WORKSPACE_OVERRIDE

    env_ws = os.getenv("HARVEY_WORKSPACE", "").strip()
    if env_ws:
        p = Path(env_ws)
        if p.is_absolute() and p.exists():
            return p.resolve()
        if (Path.cwd() / p).exists():
            return (Path.cwd() / p).resolve()
        ws_in_repo = PROJECT_ROOT / "workspaces" / p
        if ws_in_repo.exists():
            return ws_in_repo.resolve()
        if (PROJECT_ROOT / p).exists():
            return (PROJECT_ROOT / p).resolve()
        return ws_in_repo.resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "harvey.local.yaml").exists() or (cwd / "harvey.yaml").exists():
        return cwd

    return PROJECT_ROOT


def get_data_dir(workspace: Path | None = None) -> Path:
    """Get the data/ directory for the active workspace."""
    ws = workspace or get_workspace_dir()
    data_dir = ws / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path(workspace: Path | None = None) -> Path:
    """Get SQLite DB path for the active workspace."""
    return get_data_dir(workspace) / "harvey.db"

