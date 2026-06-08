"""Main L1 Support Bot orchestrator — polling loop + audit trail."""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from src.agent.auto_healer import AutoHealer
from src.agent.diagnoser import PipelineDiagnoser
from src.api.fabric_client import FabricClient
from src.models.schemas import ActionTaken, FixResult
from src.notifications.teams_notifier import TeamsNotifier
from src.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class L1SupportBot:
    """
    Production L1 support bot for Microsoft Fabric pipelines.

    Responsibilities:
      - Poll for failed pipeline runs
      - Diagnose root cause using Claude + RAG
      - Auto-fix transient errors via pipeline rerun
      - Alert Teams for non-fixable or max-retry situations
      - Maintain audit log of all actions
    """

    def __init__(
        self,
        fabric_client: FabricClient,
        diagnoser: PipelineDiagnoser,
        healer: AutoHealer,
        notifier: TeamsNotifier,
        workspace_ids: list[str],
        poll_interval_seconds: int = 300,  # 5 minutes
        audit_log_path: str = "./logs/audit.jsonl",
    ):
        self._fabric = fabric_client
        self._diagnoser = diagnoser
        self._healer = healer
        self._notifier = notifier
        self._workspaces = workspace_ids
        self._poll_interval = poll_interval_seconds
        self._audit_path = Path(audit_log_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._processed_runs: set[str] = set()  # Avoid reprocessing same run

    async def run(self):
        """Start the polling loop. Runs indefinitely."""
        logger.info(
            f"L1 Bot started. Monitoring {len(self._workspaces)} workspace(s). "
            f"Poll interval: {self._poll_interval}s"
        )
        logger.info("Entering polling loop now...")
        while True:
            try:
                logger.info("Poll cycle starting...")
                await self._poll_cycle()
                logger.info(f"Poll cycle done. Sleeping {self._poll_interval}s...")
            except Exception as e:
                logger.error(f"Poll cycle error: {e}", exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def _poll_cycle(self):
        """Single polling cycle: fetch, diagnose, fix, notify."""
        for workspace_id in self._workspaces:
            try:
                failed_runs = await self._fabric.get_failed_pipeline_runs(workspace_id)
                new_failures = [
                    r for r in failed_runs if r.run_id not in self._processed_runs
                ]
                logger.info(
                    f"Workspace {workspace_id}: {len(new_failures)} new failures found"
                )
                # Process concurrently, max 5 at once to avoid API throttling
                semaphore = asyncio.Semaphore(5)
                tasks = [
                    self._handle_failure(run, semaphore) for run in new_failures
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                logger.error(f"Error polling workspace {workspace_id}: {e}", exc_info=True)

    async def _handle_failure(self, pipeline_run, semaphore: asyncio.Semaphore):
        """Full handling lifecycle for a single failed run."""
        async with semaphore:
            run_id = pipeline_run.run_id
            self._processed_runs.add(run_id)

            try:
                # Fetch detailed logs
                logs = await self._fabric.get_run_logs(
                    pipeline_run.workspace_id,
                    pipeline_run.pipeline_id,
                    run_id,
                )

                # Diagnose with Claude + RAG
                diagnosis = await self._diagnoser.diagnose(pipeline_run, logs)

                # Attempt auto-fix
                fix_result = await self._healer.attempt_fix(diagnosis)

                # Send Teams notification
                await self._notifier.notify(fix_result)

                # Audit log
                self._write_audit(fix_result)

                logger.info(
                    f"Handled {pipeline_run.pipeline_name}/{run_id}: "
                    f"{fix_result.action_taken.value} | success={fix_result.success}"
                )

            except Exception as e:
                logger.error(
                    f"Error handling run {run_id} for {pipeline_run.pipeline_name}: {e}",
                    exc_info=True,
                )
                # Still mark as processed to avoid infinite retry of broken runs
                self._processed_runs.add(run_id)

    def _write_audit(self, fix_result: FixResult):
        """Append structured audit record to JSONL file."""
        import json
        record = {
            "timestamp": fix_result.timestamp.isoformat(),
            "pipeline_name": fix_result.diagnosis.pipeline_run.pipeline_name,
            "pipeline_id": fix_result.diagnosis.pipeline_run.pipeline_id,
            "run_id": fix_result.diagnosis.pipeline_run.run_id,
            "workspace_id": fix_result.diagnosis.pipeline_run.workspace_id,
            "error_category": fix_result.diagnosis.error_category.value,
            "is_auto_fixable": fix_result.diagnosis.is_auto_fixable,
            "error_message": fix_result.diagnosis.pipeline_run.error_message,
            "root_cause": fix_result.diagnosis.root_cause,
            "action_taken": fix_result.action_taken.value,
            "success": fix_result.success,
            "new_run_id": fix_result.new_run_id,
            "rerun_succeeded": fix_result.rerun_succeeded,
            "retry_count": fix_result.retry_count,
            "confidence_score": fix_result.diagnosis.confidence_score,
            "message": fix_result.message,
        }
        with open(self._audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
