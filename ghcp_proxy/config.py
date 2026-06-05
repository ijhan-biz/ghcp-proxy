"""설정 로더.

config.yaml 을 읽어 dataclass 로 노출한다. PyYAML 이 없으면 최소 파서로 폴백한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # mitmproxy 의존성으로 보통 함께 설치됨
except Exception:  # pragma: no cover - 폴백 경로
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class StorageConfig:
    db_path: str = "data/captures.db"
    retention_days: int = 30


@dataclass
class MaskingConfig:
    enabled: bool = True


@dataclass
class CaptureConfig:
    store_response: bool = True
    max_body_bytes: int = 1_048_576
    only_inference: bool = False


@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 10802


@dataclass
class Config:
    allowlist_hosts: list[str] = field(
        default_factory=lambda: [
            "api.githubcopilot.com",
            "copilot-proxy.githubusercontent.com",
            ".githubcopilot.com",
        ]
    )
    storage: StorageConfig = field(default_factory=StorageConfig)
    masking: MaskingConfig = field(default_factory=MaskingConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    def resolved_db_path(self) -> Path:
        p = Path(self.storage.db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def host_allowed(self, host: str) -> bool:
        host = (host or "").lower()
        for entry in self.allowlist_hosts:
            entry = entry.lower()
            if entry.startswith("."):
                if host == entry[1:] or host.endswith(entry):
                    return True
            elif host == entry:
                return True
        return False


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    raise RuntimeError("PyYAML 미설치: config.yaml 을 파싱할 수 없습니다.")


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    if path is None:
        path = os.environ.get("GHCP_CONFIG")
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return Config()
    raw = _load_yaml(cfg_path)

    storage_raw = raw.get("storage", {}) or {}
    masking_raw = raw.get("masking", {}) or {}
    capture_raw = raw.get("capture", {}) or {}
    dashboard_raw = raw.get("dashboard", {}) or {}

    return Config(
        allowlist_hosts=list(raw.get("allowlist_hosts", []) or Config().allowlist_hosts),
        storage=StorageConfig(
            db_path=storage_raw.get("db_path", "data/captures.db"),
            retention_days=int(storage_raw.get("retention_days", 30)),
        ),
        masking=MaskingConfig(enabled=bool(masking_raw.get("enabled", True))),
        capture=CaptureConfig(
            store_response=bool(capture_raw.get("store_response", True)),
            max_body_bytes=int(capture_raw.get("max_body_bytes", 1_048_576)),
            only_inference=bool(capture_raw.get("only_inference", False)),
        ),
        dashboard=DashboardConfig(
            enabled=_env_bool("GHCP_DASHBOARD", bool(dashboard_raw.get("enabled", True))),
            host=dashboard_raw.get("host", "127.0.0.1"),
            port=int(os.environ.get("GHCP_DASHBOARD_PORT", dashboard_raw.get("port", 10802))),
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off", "")
