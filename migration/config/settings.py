"""Application configuration loaded from environment variables."""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # Microsoft Fabric / AAD
    tenant_id: str = field(default_factory=lambda: os.environ["AZURE_TENANT_ID"])
    client_id: str = field(default_factory=lambda: os.environ["AZURE_CLIENT_ID"])
    client_secret: str = field(default_factory=lambda: os.environ["AZURE_CLIENT_SECRET"])

    # Claude API
    anthropic_api_key: str = field(default_factory=lambda: os.environ["ANTHROPIC_API_KEY"])

    # Teams
    teams_webhook_url: str = field(default_factory=lambda: os.environ["TEAMS_WEBHOOK_URL"])

    # Bot behaviour
    workspace_ids: list[str] = field(
        default_factory=lambda: os.environ.get(
            "FABRIC_WORKSPACE_IDS",
            "a078c6ff-84af-4f0e-b177-381e4bba48ee"  # your workspace
        ).split(",")
    )
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    )

    # Storage
    chroma_db_path: str = field(
        default_factory=lambda: os.environ.get("CHROMA_DB_PATH", "./data/chroma_db")
    )
    runbooks_dir: str = field(
        default_factory=lambda: os.environ.get("RUNBOOKS_DIR", "./runbooks")
    )
    audit_log_path: str = field(
        default_factory=lambda: os.environ.get("AUDIT_LOG_PATH", "./logs/audit.jsonl")
    )
