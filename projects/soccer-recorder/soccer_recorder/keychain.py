from __future__ import annotations

import base64
import shlex
import subprocess


class KeychainError(RuntimeError):
    """Raised when a secret cannot be saved to macOS Keychain."""


ENCODED_PREFIX = "soccer-recorder-b64:"
PARTS_PREFIX = "soccer-recorder-parts:"
KEYCHAIN_CHUNK_SIZE = 1400


def _load_raw_value(account: str, service: str) -> str | None:
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                service,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.rstrip("\r\n")
    return value or None


def _parts_count(value: str | None) -> int:
    if not value or not value.startswith(PARTS_PREFIX):
        return 0
    try:
        return max(0, int(value.removeprefix(PARTS_PREFIX)))
    except ValueError:
        return 0


def load_keychain_secret(account: str, service: str) -> str | None:
    value = _load_raw_value(account, service)
    count = _parts_count(value)
    if count:
        chunks = [_load_raw_value(account, f"{service}.part-{index:03d}") for index in range(count)]
        if any(chunk is None for chunk in chunks):
            return None
        value = "".join(str(chunk) for chunk in chunks)
    if not value:
        return None
    if value.startswith(ENCODED_PREFIX):
        try:
            decoded = base64.urlsafe_b64decode(value.removeprefix(ENCODED_PREFIX).encode("ascii"))
            return decoded.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None
    return value


def _save_raw_value(account: str, service: str, value: str) -> bool:
    command = (
        f"add-generic-password -U -a {shlex.quote(account)} -s {shlex.quote(service)} "
        f"-w {shlex.quote(value)}\n"
    )
    try:
        completed = subprocess.run(
            ["/usr/bin/security", "-i"],
            input=command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and _load_raw_value(account, service) == value


def save_keychain_secret(account: str, service: str, secret: str) -> None:
    """Save a secret without placing it in command-line arguments or logs."""
    if not account or not service or not secret:
        raise KeychainError("The Keychain account, service, and secret are required")
    if any(character in account + service for character in "\r\n\0"):
        raise KeychainError("The Keychain account or service is invalid")
    old_count = _parts_count(_load_raw_value(account, service))
    encoded_secret = ENCODED_PREFIX + base64.urlsafe_b64encode(secret.encode("utf-8")).decode("ascii")
    chunks = [
        encoded_secret[offset : offset + KEYCHAIN_CHUNK_SIZE]
        for offset in range(0, len(encoded_secret), KEYCHAIN_CHUNK_SIZE)
    ]
    if len(chunks) == 1:
        saved = _save_raw_value(account, service, chunks[0])
        new_count = 0
    else:
        saved = all(
            _save_raw_value(account, f"{service}.part-{index:03d}", chunk)
            for index, chunk in enumerate(chunks)
        ) and _save_raw_value(account, service, f"{PARTS_PREFIX}{len(chunks)}")
        new_count = len(chunks)
    if not saved or load_keychain_secret(account, service) != secret:
        raise KeychainError("macOS Keychain could not verify the saved secret")
    for index in range(new_count, old_count):
        _delete_raw_value(account, f"{service}.part-{index:03d}")


def _delete_raw_value(account: str, service: str) -> None:
    try:
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", account, "-s", service],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def delete_keychain_secret(account: str, service: str) -> None:
    count = _parts_count(_load_raw_value(account, service))
    for index in range(count):
        _delete_raw_value(account, f"{service}.part-{index:03d}")
    _delete_raw_value(account, service)
