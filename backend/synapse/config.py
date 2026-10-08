"""Runtime configuration, read once from ``SYNAPSE_*`` environment variables."""

from __future__ import annotations

import os
import re
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SAMPLES_DIR = PACKAGE_DIR.parent / "datasets"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(f"SYNAPSE_{name}")
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


def _env_list(name: str) -> tuple[str, ...]:
    value = _env(name, "") or ""
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _default_node_id() -> str:
    host = socket.gethostname().split(".")[0].lower()
    return re.sub(r"[^a-z0-9-]+", "-", host).strip("-") or "node"


def _persistent_secret(data_dir: Path, filename: str) -> str:
    """Generate a secret once and keep it in the data dir so tokens survive restarts."""
    path = data_dir / filename
    if path.exists():
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value)
    path.chmod(0o600)
    return value


@dataclass(frozen=True)
class Settings:
    node_id: str
    node_name: str
    data_dir: Path
    samples_dir: Path

    http_host: str
    http_port: int
    peer_host: str
    peer_port: int
    advertise: str
    peers: tuple[str, ...]
    cluster_secret: str

    jwt_secret: str
    jwt_ttl_hours: int
    admin_email: str | None
    admin_password: str | None
    allow_signup: bool

    seed_sample: bool
    public_url: str
    cors_origins: tuple[str, ...]
    log_level: str

    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_starttls: bool
    smtp_ssl: bool
    mail_from: str

    lsa_dims: int
    topics: int
    sample_limit: int
    ingest_workers: int
    max_upload_mb: int
    openalex_api_key: str | None

    @property
    def shard_db_path(self) -> Path:
        return self.data_dir / "shard.db"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        node_id = _env("NODE_ID") or _default_node_id()
        data_dir = Path(_env("DATA_DIR", "./data")).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        peer_port = _env_int("PEER_PORT", 7000)

        values = dict(
            node_id=node_id,
            node_name=_env("NODE_NAME", node_id),
            data_dir=data_dir,
            samples_dir=Path(_env("SAMPLES_DIR", str(DEFAULT_SAMPLES_DIR))),
            http_host=_env("HTTP_HOST", "0.0.0.0"),
            http_port=_env_int("HTTP_PORT", 8000),
            peer_host=_env("PEER_HOST", "0.0.0.0"),
            peer_port=peer_port,
            advertise=_env("ADVERTISE", f"{node_id}:{peer_port}"),
            peers=_env_list("PEERS"),
            cluster_secret=_env("CLUSTER_SECRET", ""),
            jwt_secret=_env("JWT_SECRET") or _persistent_secret(data_dir, ".jwt_secret"),
            jwt_ttl_hours=_env_int("JWT_TTL_HOURS", 24 * 7),
            admin_email=_env("ADMIN_EMAIL"),
            admin_password=_env("ADMIN_PASSWORD"),
            allow_signup=_env_bool("ALLOW_SIGNUP", True),
            seed_sample=_env_bool("SEED_SAMPLE", False),
            public_url=(_env("PUBLIC_URL", "http://localhost:3000") or "").rstrip("/"),
            cors_origins=_env_list("CORS_ORIGINS"),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            smtp_host=_env("SMTP_HOST"),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_user=_env("SMTP_USER"),
            smtp_password=_env("SMTP_PASSWORD"),
            smtp_starttls=_env_bool("SMTP_STARTTLS", False),
            smtp_ssl=_env_bool("SMTP_SSL", False),
            mail_from=_env("MAIL_FROM", "Synapse <alerts@synapse.local>"),
            lsa_dims=_env_int("LSA_DIMS", 100),
            topics=_env_int("TOPICS", 14),
            sample_limit=_env_int("SAMPLE_LIMIT", 6000),
            ingest_workers=_env_int("INGEST_WORKERS", 8),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 512),
            openalex_api_key=_env("OPENALEX_API_KEY"),
        )
        values.update(overrides)
        return cls(**values)
