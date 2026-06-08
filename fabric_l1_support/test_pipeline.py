"""
Test pipeline simulator — runs fake failures through the bot's
diagnose + heal logic without needing a real Fabric connection.

Usage:
    python test_pipeline.py
    python test_pipeline.py --scenario transient
    python test_pipeline.py --scenario schema
    python test_pipeline.py --scenario all
"""
import asyncio
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from config.settings import Settings
from src.agent.diagnoser import PipelineDiagnoser
from src.agent.auto_healer import AutoHealer
from src.api.fabric_client import FabricClient
from src.models.schemas import PipelineRun, PipelineStatus
from src.rag.knowledge_base import KnowledgeBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_pipeline")

# ── Fake pipeline runs (one per error category) ───────────────────────────────

FAKE_PIPELINES = {
    "transient": PipelineRun(
        pipeline_id="pipe-test-001",
        pipeline_name="Sales_Daily_Load",
        run_id="run-transient-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="The remote server returned an error: (429) Too Many Requests. "
                      "Retry after 60 seconds.",
        error_code="429",
    ),
    "timeout": PipelineRun(
        pipeline_id="pipe-test-002",
        pipeline_name="Inventory_Hourly_Sync",
        run_id="run-timeout-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="Operation timed out after 300 seconds waiting for source system response. "
                      "Connection reset by peer.",
        error_code="TIMEOUT",
    ),
    "auth": PipelineRun(
        pipeline_id="pipe-test-003",
        pipeline_name="Finance_Report_Pipeline",
        run_id="run-auth-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="AADSTS700082: The refresh token has expired due to inactivity. "
                      "Token expired at 2026-06-07T00:00:00Z.",
        error_code="AADSTS700082",
    ),
    "schema": PipelineRun(
        pipeline_id="pipe-test-004",
        pipeline_name="Customer_Master_ETL",
        run_id="run-schema-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="Column 'customer_email' does not exist in target table. "
                      "Schema mismatch: source has 15 columns, target has 14 columns.",
        error_code="SCHEMA_MISMATCH",
    ),
    "permission": PipelineRun(
        pipeline_id="pipe-test-005",
        pipeline_name="HR_Data_Extract",
        run_id="run-perm-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="Access to the path '/mnt/data/hr/employees.parquet' is denied. "
                      "Error code: 403 Forbidden.",
        error_code="403",
    ),
    "source_missing": PipelineRun(
        pipeline_id="pipe-test-006",
        pipeline_name="Product_Catalog_Load",
        run_id="run-missing-001",
        workspace_id="a078c6ff-84af-4f0e-b177-381e4bba48ee",
        status=PipelineStatus.FAILED,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        error_message="FileNotFoundException: The file 'products_20260607.csv' was not found "
                      "in Azure Blob Storage container 'raw-data'.",
        error_code="FileNotFoundException",
    ),
}

FAKE_LOGS = {
    "transient": """
[2026-06-07 10:00:01] INFO  Starting pipeline Sales_Daily_Load
[2026-06-07 10:00:05] INFO  Connecting to source SQL Server...
[2026-06-07 10:00:06] INFO  Reading 500,000 rows from dbo.sales_fact
[2026-06-07 10:02:30] ERROR HttpRequestException: Response status code 429
[2026-06-07 10:02:30] ERROR Retry-After: 60
[2026-06-07 10:02:30] ERROR Pipeline failed after 3 retries
""",
    "timeout": """
[2026-06-07 11:00:00] INFO  Starting pipeline Inventory_Hourly_Sync
[2026-06-07 11:00:02] INFO  Connecting to SAP source system...
[2026-06-07 11:05:02] ERROR System.TimeoutException: The operation timed out after 300s
[2026-06-07 11:05:02] ERROR Connection reset by peer at 10.0.1.45:8080
[2026-06-07 11:05:02] ERROR Pipeline aborted
""",
    "auth": """
[2026-06-07 09:00:00] INFO  Starting pipeline Finance_Report_Pipeline
[2026-06-07 09:00:01] INFO  Acquiring AAD token...
[2026-06-07 09:00:02] ERROR AADSTS700082: The refresh token has expired
[2026-06-07 09:00:02] ERROR Token last used: 2026-05-07T09:00:00Z (31 days ago)
[2026-06-07 09:00:02] ERROR Authentication failed - pipeline aborted
""",
    "schema": """
[2026-06-07 08:00:00] INFO  Starting pipeline Customer_Master_ETL
[2026-06-07 08:00:05] INFO  Reading source table CRM.dbo.customers (15 columns)
[2026-06-07 08:00:10] INFO  Mapping to target table DW.dbo.dim_customer (14 columns)
[2026-06-07 08:00:10] ERROR Column mapping failed: 'customer_email' not found in target
[2026-06-07 08:00:10] ERROR Source schema: id, name, email, customer_email, phone, ...
[2026-06-07 08:00:10] ERROR Target schema: id, name, email, phone, ...
[2026-06-07 08:00:10] ERROR Pipeline failed - schema mismatch requires manual fix
""",
    "permission": """
[2026-06-07 07:00:00] INFO  Starting pipeline HR_Data_Extract
[2026-06-07 07:00:02] INFO  Attempting to read /mnt/data/hr/employees.parquet
[2026-06-07 07:00:03] ERROR IOException: Access to path is denied (HTTP 403)
[2026-06-07 07:00:03] ERROR Service Principal 'fabric-bot-sp' lacks Storage Blob Data Reader role
[2026-06-07 07:00:03] ERROR Pipeline failed - permission denied
""",
    "source_missing": """
[2026-06-07 06:00:00] INFO  Starting pipeline Product_Catalog_Load
[2026-06-07 06:00:02] INFO  Looking for products_20260607.csv in container raw-data
[2026-06-07 06:00:03] ERROR BlobNotFoundException: products_20260607.csv not found
[2026-06-07 06:00:03] ERROR Container: raw-data | Account: datalakeprod
[2026-06-07 06:00:03] ERROR Pipeline failed - source file missing
""",
}


# ── Mock auto-healer that does NOT call real Fabric API ───────────────────────

class MockAutoHealer(AutoHealer):
    """Healer that simulates reruns instead of calling Fabric API."""

    async def attempt_fix(self, diagnosis):
        run = diagnosis.pipeline_run
        pipeline_id = run.pipeline_id
        retry_count = self._retries.get(pipeline_id, 0)

        from src.models.schemas import ActionTaken, FixResult

        if retry_count >= 3:
            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.MAX_RETRIES,
                new_run_id=None,
                success=False,
                message=f"Max retries (3) exceeded. Escalated to L2.",
                retry_count=retry_count,
            )

        if not diagnosis.is_auto_fixable:
            return FixResult(
                diagnosis=diagnosis,
                action_taken=ActionTaken.ALERT_SENT,
                new_run_id=None,
                success=False,
                message=f"Manual intervention required. Root cause: {diagnosis.root_cause}",
                retry_count=retry_count,
            )

        # Simulate successful rerun
        fake_run_id = f"run-rerun-{pipeline_id[-3:]}-{retry_count+1:03d}"
        self._retries[pipeline_id] = retry_count + 1
        self._kb.add_resolved_incident(
            error_message=run.error_message or "",
            root_cause=diagnosis.root_cause,
            resolution=f"[TEST] Auto-rerun triggered. Fake run_id: {fake_run_id}",
            pipeline_name=run.pipeline_name,
        )
        return FixResult(
            diagnosis=diagnosis,
            action_taken=ActionTaken.AUTO_RERUN,
            new_run_id=fake_run_id,
            success=True,
            message=f"[TEST] Pipeline rerun triggered. New run ID: {fake_run_id}",
            retry_count=retry_count + 1,
        )


# ── Runner ────────────────────────────────────────────────────────────────────

def print_result(scenario: str, fix_result):
    d = fix_result.diagnosis
    run = d.pipeline_run
    status = "✅ AUTO-FIXED" if fix_result.success else "🚨 NEEDS ATTENTION"

    print(f"\n{'='*60}")
    print(f"  SCENARIO : {scenario.upper()}")
    print(f"  Pipeline : {run.pipeline_name}")
    print(f"  Status   : {status}")
    print(f"  Category : {d.error_category.value}")
    print(f"  Fixable  : {d.is_auto_fixable}")
    print(f"  Action   : {fix_result.action_taken.value}")
    print(f"  Confidence: {int(d.confidence_score*100)}%")
    print(f"  Root Cause: {d.root_cause}")
    print(f"  Message  : {fix_result.message}")
    if fix_result.new_run_id:
        print(f"  New Run  : {fix_result.new_run_id}")
    print(f"{'='*60}")


async def run_scenario(scenario: str, diagnoser: PipelineDiagnoser, healer: MockAutoHealer):
    pipeline_run = FAKE_PIPELINES[scenario]
    logs = FAKE_LOGS[scenario]

    logger.info(f"Running scenario: {scenario} — {pipeline_run.pipeline_name}")
    diagnosis = await diagnoser.diagnose(pipeline_run, logs)
    fix_result = await healer.attempt_fix(diagnosis)
    print_result(scenario, fix_result)
    return fix_result


async def main(scenarios: list[str]):
    settings = Settings()

    kb = KnowledgeBase(db_path=settings.chroma_db_path)
    kb.index_runbooks(settings.runbooks_dir)

    diagnoser = PipelineDiagnoser(
        api_key=settings.anthropic_api_key,
        knowledge_base=kb,
    )
    retry_tracker: dict = {}
    healer = MockAutoHealer(
        fabric_client=None,
        knowledge_base=kb,
        retry_tracker=retry_tracker,
    )

    print(f"\n🤖 Fabric L1 Bot — Pipeline Test Runner")
    print(f"   Testing {len(scenarios)} scenario(s): {', '.join(scenarios)}\n")

    results = []
    for s in scenarios:
        result = await run_scenario(s, diagnoser, healer)
        results.append((s, result))

    # Summary
    print(f"\n{'─'*60}")
    print(f"  SUMMARY")
    print(f"{'─'*60}")
    for s, r in results:
        icon = "✅" if r.success else ("🔴" if not r.diagnosis.is_auto_fixable else "⚠️")
        print(f"  {icon}  {s:<16} → {r.action_taken.value}")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Fabric L1 bot pipeline scenarios")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=list(FAKE_PIPELINES.keys()) + ["all"],
        help="Which failure scenario to test (default: all)",
    )
    args = parser.parse_args()

    scenarios = list(FAKE_PIPELINES.keys()) if args.scenario == "all" else [args.scenario]
    asyncio.run(main(scenarios))
