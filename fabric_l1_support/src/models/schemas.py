from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PipelineStatus(str, Enum):
    FAILED = "Failed"
    SUCCEEDED = "Succeeded"
    RUNNING = "Running"
    CANCELLED = "Cancelled"


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"          # Auto-fixable: timeouts, throttling
    AUTH = "auth"                    # Semi-auto: token refresh + rerun
    INFRA = "infra"                  # Auto-fixable: temp unavailability
    SCHEMA = "schema"                # Manual: schema mismatch
    PERMISSION = "permission"        # Manual: access denied
    DATA_QUALITY = "data_quality"    # Manual: bad data
    SOURCE_MISSING = "source_missing"  # Manual: file/table not found
    UNKNOWN = "unknown"              # Manual: unclassified


class ActionTaken(str, Enum):
    AUTO_RERUN = "auto_rerun"
    ALERT_SENT = "alert_sent"
    MAX_RETRIES = "max_retries_exceeded"
    INVESTIGATING = "investigating"


@dataclass
class PipelineRun:
    pipeline_id: str
    pipeline_name: str
    run_id: str
    workspace_id: str
    status: PipelineStatus
    start_time: datetime
    end_time: Optional[datetime]
    error_message: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class DiagnosisResult:
    pipeline_run: PipelineRun
    error_category: ErrorCategory
    is_auto_fixable: bool
    root_cause: str
    recommended_action: str
    confidence_score: float
    similar_past_errors: list[dict] = field(default_factory=list)
    runbook_references: list[str] = field(default_factory=list)


@dataclass
class FixResult:
    diagnosis: DiagnosisResult
    action_taken: ActionTaken
    new_run_id: Optional[str]
    success: bool
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
