"""Subprocess helper for Agent Reach upstream CLIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from btcpoly.retries import RetryError, retry

_SKIP_MARKERS = (
    "BROWSER_CONNECT",
    "Browser Bridge",
    "not connected",
    "not on PATH",
    "not installed",
    "TWITTER_AUTH_TOKEN and TWITTER_CT0 are not set",
    "No Twitter cookies found",
    "not_authenticated",
    "login required",
    "AUTH_REQUIRED",
    "login wall",
    "ClientTransaction",
    "Failed to init ClientTransaction",
    "twitter_cli.client",
    "Unsupported url scheme",
    "API rate limit exceeded",
    "rate limit exceeded",
    "HTTP 403",
    "secondary rate limit",
)
_SKIP_EXIT_CODES = {69, 127}


class SkipChannel(Exception):
    """Channel is unavailable (missing binary, cookies, etc.). Not a hard failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _binary_names(name: str) -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{name}.exe", f"{name}.cmd", f"{name}.bat", name)
    return (name,)


def extra_binary_candidates(name: str) -> list[Path]:
    """Look next to this Python and in Windows user Scripts (pip --user)."""
    dirs = [Path(sys.executable).resolve().parent]
    roaming = Path(os.environ.get("APPDATA") or "") / "Python"
    if roaming.is_dir():
        dirs.extend(sorted(roaming.glob("Python*/Scripts"), reverse=True))
    found: list[Path] = []
    seen: set[str] = set()
    for folder in dirs:
        for filename in _binary_names(name):
            candidate = folder / filename
            key = str(candidate).lower()
            if key in seen or not candidate.is_file():
                continue
            seen.add(key)
            found.append(candidate)
    return found


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    extras = extra_binary_candidates(name)
    if extras:
        return str(extras[0])
    raise SkipChannel(f"{name} not on PATH")


def skip_reason_from_cli(output: str, returncode: int) -> str | None:
    blob = (output or "").strip()
    if returncode in _SKIP_EXIT_CODES:
        return blob[:240] or f"exit {returncode}"
    lower = blob.lower()
    for marker in _SKIP_MARKERS:
        if marker.lower() in lower:
            return blob[:240] or marker
    return None


def parse_cli_output(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    lines: list[Any] = []
    json_lines = True
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            json_lines = False
            break
    if json_lines and lines:
        return lines
    try:
        parsed = yaml.safe_load(text)
        if parsed is not None:
            return parsed
    except yaml.YAMLError:
        pass
    return [{"text": text}]


def run_cli(
    command: list[str],
    *,
    timeout: int,
    env: dict[str, str] | None = None,
    attempts: int = 1,
) -> Any:
    resolved = require_binary(command[0])
    argv = [resolved, *command[1:]]
    merged = os.environ.copy()
    if env:
        merged.update({k: v for k, v in env.items() if v is not None})

    def _run() -> str:
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=merged,
            )
        except FileNotFoundError as exc:
            raise SkipChannel(f"{command[0]} not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise SkipChannel(f"{command[0]} timed out") from exc
        err = (completed.stderr or completed.stdout or "").strip()
        if completed.returncode != 0:
            skip = skip_reason_from_cli(err, completed.returncode)
            if skip:
                raise SkipChannel(skip)
            raise RuntimeError(err[:500] or f"exit {completed.returncode}")
        return completed.stdout or ""

    try:
        stdout = retry(
            _run,
            attempts=max(1, attempts),
            retry_on=(RuntimeError,),
        )
    except SkipChannel:
        raise
    except RetryError as exc:
        raise RuntimeError(str(exc)) from exc
    return parse_cli_output(stdout)
