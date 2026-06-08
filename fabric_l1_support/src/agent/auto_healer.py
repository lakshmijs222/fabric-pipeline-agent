"""Auto-healing engine: decides and executes fixes for failed pipelines."""
import logging
from datetime import datetime

from src.api.fabric_client import FabricClient
from src.models.schemas import ActionTaken, DiagnosisResult, FixResult
from src.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

MAX_RETRIES_PER_PIPELINE = 3
RETRY_BACKOFF_SECONDS = {1: 60, 2: 300, 3: 900}  # 1m, 5m, 15m


class AutoHealer:
    """Executes auto-fix actions for diagnosed pipeline failures."""

    def __init__(
        self,
        fabric_client: FabricClient,
        knowledge_base: KnowledgeBase,
        retry_tracker: dict,  # {pipeline_id: retry_count}
    ):
        self._fabric = fabric_client
        self._kb = knowledge_base
        self._retries = retry_tracker

    async def attempt_fix(self, diagnosis: DiagnosisResult) -> FixResult:
        """Attempt automated fix based on diagnosis. Returns FixResult."""
        run = diagnosis.pipeline_run
        pipeline_id = run.pipeline_id
        retry_count = self._retries.get(pipeline_id, 0)

        # Check retry limit
        if retry_count >= MAX_RETRIES_PER_PIPELINE:
            logger.warning(
                f"Pipeline {run.pipeline_name} exceeded max retries ({MAX_RETRIES_PER_PIPELINE})"
            )
            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.MAX_RETRIES,
                new_run_id=None,
                success=False,
                message=(
                    f"Max retries ({MAX_RETRIES_PER_PIPELINE}) exceeded. "
                    f"Pipeline escalated to L2 support."
                ),
                retry_count=retry_count,
            )

        if not diagnosis.is_auto_fixable:
            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.ALERT_SENT,
                new_run_id=None,
                success=False,
                message=(
                    f"Error category '{diagnosis.error_category.value}' requires manual intervention. "
                    f"Root cause: {diagnosis.root_cause}"
                ),
                retry_count=retry_count,
            )

        # Execute auto-fix: trigger pipeline rerun
        logger.info(
            f"Auto-fixing pipeline {run.pipeline_name} "
            f"(attempt {retry_count + 1}/{MAX_RETRIES_PER_PIPELINE})"
        )

        new_run_id = await self._fabric.rerun_pipeline(run.workspace_id, pipeline_id)

        if new_run_id:
            self._retries[pipeline_id] = retry_count + 1

            # Record successful resolution in KB for future reference
            self._kb.add_resolved_incident(
                error_message=run.error_message or "",
                root_cause=diagnosis.root_cause,
                resolution=f"Auto-rerun triggered. New run_id: {new_run_id}",
                pipeline_name=run.pipeline_name,
            )

            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.AUTO_RERUN,
                new_run_id=new_run_id,
                success=True,
                message=(
                    f"Pipeline auto-fixed. New run triggered. "
                    f"Run ID: {new_run_id} "
                    f"(Attempt {retry_count + 1}/{MAX_RETRIES_PER_PIPELINE})"
                ),
                retry_count=retry_count + 1,
            )
        else:
            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.ALERT_SENT,
                new_run_id=None,
                success=False,
                message="Rerun API call failed. Manual intervention required.",
                retry_count=retry_count,
            )

    def reset_retries(self, pipeline_id: str):
        """Reset retry counter when pipeline succeeds."""
        self._retries.pop(pipeline_id, None)
