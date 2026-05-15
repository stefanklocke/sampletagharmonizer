from __future__ import annotations

import shlex
from os import environ
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    """Read a small dotenv file with shell-like quoting support."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            parsed = shlex.split(line, comments=True, posix=True)
        except ValueError:
            parsed = [line]
        if not parsed or "=" not in parsed[0]:
            continue
        key, value = parsed[0].split("=", 1)
        values[key] = value
    return values


def dataset_path_from_env(env_path: Path, key: str = "DATASET_PATH_NI") -> Path:
    values = load_env(env_path)
    if key in environ:
        return Path(environ[key]).expanduser()
    try:
        return Path(values[key]).expanduser()
    except KeyError as exc:
        raise KeyError(f"{key} not found in {env_path}") from exc


def database_url_from_env(env_path: Path, key: str = "DATABASE_URL") -> str:
    values = load_env(env_path)
    if key in environ:
        return environ[key]
    try:
        return values[key]
    except KeyError as exc:
        raise KeyError(f"{key} not found in environment or {env_path}") from exc
