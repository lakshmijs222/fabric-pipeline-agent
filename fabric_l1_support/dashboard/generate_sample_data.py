"""Generate sample audit data for dashboard testing."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

Path("logs").mkdir(exist_ok=True)

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
            "root_cause": root_cause,
            "action_taken": action,
            "success": success,
            "new_run_id": f"run_{random.randint(100000, 999999)}" if success else None,
            "retry_count": retry_count,
            "confidence_score": round(random.uniform(0.72, 0.99), 2),
            "message": f"{'Auto-fixed' if success else 'Escalated'}: {root_cause}",
        })

out = Path("logs/audit.jsonl")
with open(out, "w", encoding="utf-8") as f:
    for r in sorted(records, key=lambda x: x["timestamp"]):
        f.write(json.dumps(r) + "\n")

print(f"Generated {len(records)} sample incidents -> {out}")
