"""Generate sample audit data for dashboard testing / public demo.

Importable: `build_sample_records()` returns the records in memory (used by the
dashboard as a fallback when no real audit log exists, e.g. on Streamlit Cloud).
Run as a script to also write them to logs/audit.jsonl.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

PIPELINES = [
    "load_sales_fact", "transform_customer_dim", "ingest_finance_raw",
    "load_inventory_delta", "sync_hr_data", "aggregate_marketing_kpi",
    "refresh_product_catalog", "load_azure_sql_orders", "dataflow_crm_sync",
    "load_powerbi_dataset",
]
CATEGORIES = {
    "transient": (0.35, True),
    "auth": (0.15, True),
    "infra": (0.10, True),
    "schema": (0.15, False),
    "permission": (0.10, False),
    "data_quality": (0.08, False),
    "source_missing": (0.05, False),
    "unknown": (0.02, False),
}
ACTIONS = {
    True: ["auto_rerun"],
    False: ["alert_sent", "max_retries_exceeded"],
}
ROOT_CAUSES = {
    "transient": ["Fabric capacity timeout after 30s", "HTTP 429 rate limit from source API", "Connection pool exhausted"],
    "auth": ["AAD token expired during run", "Service principal secret rotated", "Certificate thumbprint mismatch"],
    "infra": ["Source SQL Server temporarily unavailable (503)", "ADLS Gen2 endpoint returned 503"],
    "schema": ["Column 'order_date' not found in source", "Type mismatch: expected INT got VARCHAR", "New column added to source breaking sink"],
    "permission": ["Service principal lacks Storage Blob Data Reader", "RBAC role removed from Lakehouse", "IP whitelist blocking SP"],
    "data_quality": ["NULL constraint violation on column 'customer_id'", "Duplicate key on primary key constraint", "Check constraint failed: amount > 0"],
    "source_missing": ["Source file '/raw/2024/sales.parquet' not found", "Lakehouse table 'stg_orders' does not exist"],
    "unknown": ["Internal Fabric engine error 0x8004005", "Unexpected crash in activity worker"],
}
ERROR_MESSAGES = {
    "transient": [
        "OperationTimeout: Activity 'CopyData' timed out after 30s waiting for Fabric capacity.",
        "TooManyRequests (429): Rate limit exceeded calling source REST API.",
        "Connection pool exhausted: no available connections in pool (max=100).",
    ],
    "auth": [
        "AuthenticationFailed (401): AAD token expired during pipeline execution.",
        "TokenExpired: Service principal secret was rotated; bearer token rejected.",
        "AADSTS700027: Certificate thumbprint mismatch for service principal.",
    ],
    "infra": [
        "ServiceUnavailable (503): Source SQL Server temporarily unavailable.",
        "ADLS Gen2 endpoint returned 503 ServiceUnavailable.",
    ],
    "schema": [
        "SchemaError: Column 'order_date' not found in source dataset.",
        "DataTypeConversion: expected INT but received VARCHAR for column 'amount'.",
        "ColumnNotFound: new column added to source breaks sink mapping.",
    ],
    "permission": [
        "AccessDenied (403): Service principal lacks 'Storage Blob Data Reader' on ADLS.",
        "Forbidden (403): RBAC role removed from Lakehouse 'SQL_Migration_LH'.",
        "PermissionDenied: source IP blocked by firewall whitelist.",
    ],
    "data_quality": [
        "NullConstraintViolation: column 'customer_id' contains NULL values.",
        "DuplicateKey: primary key constraint violated on 'order_id'.",
        "CheckConstraint failed: amount > 0 violated by 14 rows.",
    ],
    "source_missing": [
        "FileNotFound: source file '/raw/2024/sales.parquet' does not exist.",
        "TableNotFoundException: Lakehouse table 'stg_orders' does not exist.",
    ],
    "unknown": [
        "Internal Fabric engine error 0x8004005 (no further detail).",
        "Unexpected crash in activity worker; correlationId unavailable.",
    ],
}

def build_sample_records() -> list[dict]:
    """Build 30 days of realistic sample incidents in memory."""
    records = []
    now = datetime.utcnow()

    for day_offset in range(30):  # 30 days of data
        day = now - timedelta(days=day_offset)
        # More failures on weekdays, fewer on weekends
        weekday = day.weekday()
        num_incidents = random.randint(2, 8) if weekday < 5 else random.randint(0, 3)

        for _ in range(num_incidents):
            hour = random.choices(
                range(24),
                weights=[1,1,1,1,2,3,4,5,6,6,5,4,3,3,3,4,5,6,5,4,3,2,1,1],
            )[0]
            ts = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))

            pipeline = random.choice(PIPELINES)
            category = random.choices(
                list(CATEGORIES.keys()),
                weights=[v[0] for v in CATEGORIES.values()],
            )[0]
            is_fixable, _ = CATEGORIES[category]

            if is_fixable:
                retry_count = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
                action = "auto_rerun" if retry_count < 3 else "max_retries_exceeded"
                success = action == "auto_rerun"
            else:
                retry_count = 0
                action = "alert_sent"
                success = False

            root_cause = random.choice(ROOT_CAUSES[category])
            error_message = random.choice(ERROR_MESSAGES[category])
            # Verified outcome of the rerun: True=recovered, False=failed again,
            # None=no rerun / still running.
            if action == "auto_rerun":
                rerun_succeeded = random.choices([True, False, None], weights=[0.8, 0.1, 0.1])[0]
            elif action == "max_retries_exceeded":
                rerun_succeeded = False
            else:
                rerun_succeeded = None
            pipeline_id = f"pip_{abs(hash(pipeline)) % 100000:05d}"
            workspace_id = random.choice(["ws-prod-001", "ws-prod-002", "ws-dev-001"])

            records.append({
                "timestamp": ts.isoformat() + "Z",
                "pipeline_name": pipeline,
                "pipeline_id": pipeline_id,
                "run_id": f"run_{abs(hash(ts.isoformat() + pipeline)) % 1000000:06d}",
                "workspace_id": workspace_id,
                "error_category": category,
                "is_auto_fixable": is_fixable,
                "error_message": error_message,
                "root_cause": root_cause,
                "action_taken": action,
                "success": success,
                "new_run_id": f"run_{random.randint(100000, 999999)}" if success else None,
                "rerun_succeeded": rerun_succeeded,
                "retry_count": retry_count,
                "confidence_score": round(random.uniform(0.72, 0.99), 2),
                "message": f"{'Auto-fixed' if success else 'Escalated'}: {root_cause}",
            })

    return sorted(records, key=lambda x: x["timestamp"])


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    out = Path("logs/audit.jsonl")
    records = build_sample_records()
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Generated {len(records)} sample incidents -> {out}")
