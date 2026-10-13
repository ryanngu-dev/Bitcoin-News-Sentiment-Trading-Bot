from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from btcpoly.config import Settings


@dataclass
class AgentReachHealth:
    installed: bool
    executable: str | None
    ok: bool
    message: str
    channels: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | list[Any] | None = None
    returncode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "executable": self.executable,
            "ok": self.ok,
            "message": self.message,
            "channels": self.channels,
            "returncode": self.returncode,
        }


def _extract_channels(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        for key in ("channels", "status", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return nested
        # doctor --json may be a flat {twitter: {...}, youtube: {...}} map
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return payload
    return {}


def check_agent_reach(settings: Settings) -> AgentReachHealth:
    cmd = list(settings.agent_reach.doctor_command)
    executable = shutil.which(cmd[0]) if cmd else None
    if executable is None:
        return AgentReachHealth(
            installed=False,
            executable=None,
            ok=False,
            message=(
                "agent-reach is not on PATH. Install from GitHub (not PyPI): "
                "pip install https://github.com/Panniantong/agent-reach/archive/main.zip"
            ),
        )
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.agent_reach.doctor_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return AgentReachHealth(
            installed=True,
            executable=executable,
            ok=False,
            message=f"agent-reach doctor timed out after {settings.agent_reach.doctor_timeout_seconds}s",
        )
    except OSError as exc:
        return AgentReachHealth(
            installed=True,
            executable=executable,
            ok=False,
            message=f"failed to run agent-reach doctor: {exc}",
        )

    stdout = (completed.stdout or "").strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    channels = _extract_channels(payload)
    ok = completed.returncode == 0
    message = "agent-reach doctor completed"
    if not ok:
        err = (completed.stderr or stdout or "non-zero exit").strip().splitlines()
        message = err[-1] if err else "agent-reach doctor failed"
    return AgentReachHealth(
        installed=True,
        executable=executable,
        ok=ok,
        message=message,
        channels=channels,
        raw=payload if isinstance(payload, (dict, list)) else None,
        returncode=completed.returncode,
    )
