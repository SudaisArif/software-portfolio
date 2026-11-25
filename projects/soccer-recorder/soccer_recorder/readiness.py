from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MacReadiness:
    worker_running: bool
    sleep_prevention_active: bool
    power_connected: bool | None
    lid_open: bool | None

    @property
    def issues(self) -> tuple[str, ...]:
        problems: list[str] = []
        if not self.worker_running:
            problems.append("Background recorder is not running; schedule a game or click Retry.")
        if self.worker_running and not self.sleep_prevention_active:
            problems.append("macOS sleep prevention is not active; select a game and click Retry.")
        if self.power_connected is False:
            problems.append("Connect the Mac to its power adapter so its battery cannot run out.")
        elif self.power_connected is None:
            problems.append("The app could not verify that the Mac is connected to power.")
        if self.lid_open is False:
            problems.append("Open the MacBook lid; closing it can suspend background recording.")
        return tuple(problems)

    @property
    def ready(self) -> bool:
        return not self.issues

    def details(self) -> str:
        power = "Connected" if self.power_connected else "Not connected"
        if self.power_connected is None:
            power = "Could not verify"
        lid = "Open" if self.lid_open else "Closed"
        if self.lid_open is None:
            lid = "Not applicable / could not detect"
        lines = (
            f"Background recorder: {'Running' if self.worker_running else 'Not running'}",
            f"Sleep prevention: {'Active' if self.sleep_prevention_active else 'Not active'}",
            f"Power adapter: {power}",
            f"MacBook lid: {lid}",
        )
        if self.ready:
            return "\n".join((*lines, "", "This Mac is ready for unattended recording."))
        return "\n".join((*lines, "", "Fix before leaving:", *(f"• {issue}" for issue in self.issues)))


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def parse_sleep_prevention(output: str) -> bool:
    lowered = output.casefold()
    has_system_assertion = bool(re.search(r"PreventUserIdleSystemSleep\s+1", output))
    return has_system_assertion and "caffeinate command-line tool" in lowered and "soccer recorder" in lowered


def parse_power_connected(output: str) -> bool | None:
    match = re.search(r"Now drawing from ['\"]([^'\"]+)", output, flags=re.IGNORECASE)
    if not match:
        return None
    source = match.group(1).casefold()
    return "ac power" in source or "power adapter" in source


def parse_lid_open(output: str) -> bool | None:
    match = re.search(r'"AppleClamshellState"\s*=\s*(Yes|No)', output, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).casefold() == "no"


def sleep_prevention_active() -> bool:
    return parse_sleep_prevention(_command_output(["/usr/bin/pmset", "-g", "assertions"]))


def power_adapter_connected() -> bool | None:
    return parse_power_connected(_command_output(["/usr/bin/pmset", "-g", "batt"]))


def macbook_lid_open() -> bool | None:
    return parse_lid_open(
        _command_output(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
    )


def check_mac_readiness(worker_running: bool) -> MacReadiness:
    return MacReadiness(
        worker_running=worker_running,
        sleep_prevention_active=sleep_prevention_active() if worker_running else False,
        power_connected=power_adapter_connected(),
        lid_open=macbook_lid_open(),
    )
