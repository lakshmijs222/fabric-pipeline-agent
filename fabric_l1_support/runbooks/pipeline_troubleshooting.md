# Fabric Pipeline Troubleshooting Runbook

## Triage Decision Tree

### Step 1: Check error category
- **Transient** (timeout, throttling, 503) → Auto-rerun, max 3 attempts
- **Auth** (401, token expired) → Refresh token + rerun
- **Schema** (column not found, type mismatch) → L2 escalation required
- **Permission** (403, access denied) → L2 escalation, check SP role assignments
- **Source Missing** (404, file not found) → Check upstream pipeline status
- **Data Quality** → DQ team escalation

## Common Fabric-Specific Errors

### Lakehouse Copy Activity Failures
- If error contains "DeltaTableNotFound" → Source Lakehouse table not yet created by upstream
- If error contains "ConcurrentModification" → Another pipeline writing simultaneously, rerun in 5 min
- If error contains "LakehouseCapacityExceeded" → Transient, rerun

### Dataflow Gen2 Failures
- If "Mashup evaluation error" → Data transformation logic error, manual fix
- If "Gateway timeout" → Transient, rerun
- If "Credential refresh failed" → Auth issue, check data source credentials in Fabric

### Warehouse Copy Failures
- If "DWU limit exceeded" → Scale up warehouse or rerun during off-peak
- If "Login failed" → SP credentials issue, not auto-fixable

## Escalation Matrix

| Category | L1 Bot Action | L2 Action Required |
|---|---|---|
| Transient | Auto-rerun (3x) | If all 3 fail |
| Auth | Refresh + rerun | If refresh fails |
| Schema | Alert L2 | Update schema mapping |
| Permission | Alert L2 | Grant RBAC permissions |
| Source Missing | Alert L2 | Fix upstream pipeline |
| Data Quality | Alert DQ team | Cleanse source data |
| Unknown | Alert L2 | Investigate |

## SLA Targets
- L1 Bot response time: < 5 minutes from failure detection
- Auto-fix resolution: < 15 minutes (including retries)
- L2 escalation: Within 30 minutes if no auto-fix
- Critical pipelines: Immediate Teams alert + oncall page
