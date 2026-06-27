import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class CredentialStore(Protocol):
    def set(self, ref: str, secret: str) -> None:
        ...

    def get(self, ref: str) -> str:
        ...


class KeychainCredentialStore:
    def __init__(self, service: str = "SiftBackend") -> None:
        self.service = service

    def set(self, ref: str, secret: str) -> None:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a",
                ref,
                "-s",
                self.service,
                "-w",
                secret,
                "-U",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def get(self, ref: str) -> str:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                ref,
                "-s",
                self.service,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""


class FileCredentialStore:
    """Dev/test credential store used only with explicit local paths."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def set(self, ref: str, secret: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(ref)
        path.write_text(secret, encoding="utf-8")
        os.chmod(path, 0o600)

    def get(self, ref: str) -> str:
        path = self._path(ref)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _path(self, ref: str) -> Path:
        safe_ref = re.sub(r"[^a-zA-Z0-9_.:-]", "_", ref)
        return self.directory / safe_ref


def credential_store_for_settings_path(settings_path: Path) -> CredentialStore:
    if explicit_path := os.environ.get("SIFT_CREDENTIAL_STORE_PATH"):
        return FileCredentialStore(Path(explicit_path))
    if os.environ.get("SIFT_PROVIDER_SETTINGS_PATH"):
        return FileCredentialStore(settings_path.parent / ".credentials")
    if shutil.which("security"):
        return KeychainCredentialStore()
    return FileCredentialStore(settings_path.parent / ".credentials")


def credential_ref(kind: str, provider: str, *, user_id: str = "local-dev") -> str:
    normalized_user = re.sub(r"[^a-z0-9_.:-]", "_", user_id.strip().lower() or "local-dev")
    normalized_kind = re.sub(r"[^a-z0-9_.:-]", "_", kind.strip().lower())
    normalized_provider = re.sub(r"[^a-z0-9_.:-]", "_", provider.strip().lower())
    return f"user:{normalized_user}:{normalized_kind}:{normalized_provider}:api_key"


def legacy_credential_ref(kind: str, provider: str) -> str:
    normalized_kind = re.sub(r"[^a-z0-9_.:-]", "_", kind.strip().lower())
    normalized_provider = re.sub(r"[^a-z0-9_.:-]", "_", provider.strip().lower())
    return f"{normalized_kind}:{normalized_provider}:api_key"
