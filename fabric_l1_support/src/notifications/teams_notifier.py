"""Microsoft Teams notification via Adaptive Cards."""
import logging
from datetime import datetime

import httpx

from src.models.schemas import ActionTaken, FixResult

logger = logging.getLogger(__name__)

# Color codes for Adaptive Card header
ACTION_COLORS = {
    ActionTaken.AUTO_RERUN: "Good",       # Green
    ActionTaken.ALERT_SENT: "Attention",   # Yellow
    ActionTaken.MAX_RETRIES: "Warning",    # Red
    ActionTaken.INVESTIGATING: "Emphasis", # Blue
}


class TeamsNotifier:
    """Sends Adaptive Card notifications to a Teams channel via webhook."""

    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url
        self._http = httpx.AsyncClient(timeout=10.0)

    async def notify(self, fix_result: FixResult):
        """Send fix result notification to Teams channel."""
        card = self._build_adaptive_card(fix_result)
        try:
            resp = await self._http.post(self._webhook_url, json=card)
            resp.raise_for_status()
            logger.info(f"Teams notification sent for {fix_result.diagnosis.pipeline_run.pipeline_name}")
        except httpx.HTTPError as e:
            logger.error(f"Failed to send Teams notification: {e}")

    def _build_adaptive_card(self, fix_result: FixResult) -> dict:
        run = fix_result.diagnosis.pipeline_run
        diagnosis = fix_result.diagnosis
        color = ACTION_COLORS.get(fix_result.action_taken, "Default")
        icon = "✅" if fix_result.success else "🚨"
        action_label = fix_result.action_taken.value.replace("_", " ").title()

        return {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "Container",
                            "style": color,
                            "items": [{
                                "type": "TextBlock",
                                "text": f"{icon} Fabric L1 Bot — {action_label}",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Light",
                            }],
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Pipeline", "value": run.pipeline_name},
                                {"title": "Workspace", "value": run.workspace_id},
                                {"title": "Error Category", "value": diagnosis.error_category.value},
                                {"title": "Confidence", "value": f"{int(diagnosis.confidence_score * 100)}%"},
                                {"title": "Retry Attempt", "value": f"{fix_result.retry_count}/3"},
                                {"title": "Time", "value": fix_result.timestamp.strftime("%Y-%m-%d %H:%M UTC")},
                            ],
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Root Cause:** {diagnosis.root_cause}",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Action:** {fix_result.message}",
                            "wrap": True,
                        },
                    ] + ([{
                        "type": "TextBlock",
                        "text": f"**New Run ID:** `{fix_result.new_run_id}`",
                        "color": "Good",
                    }] if fix_result.new_run_id else []) + ([{
                        "type": "TextBlock",
                        "text": f"⚠️ **Recommended Action:** {diagnosis.recommended_action}",
                        "color": "Attention",
                        "wrap": True,
                    }] if not fix_result.success else []),
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "View in Fabric",
                            "url": (
                                f"https://app.fabric.microsoft.com/groups/"
                                f"{run.workspace_id}/datapipelines/{run.pipeline_id}"
                                f"?experience=fabric-developer"
                            ),
                        },
                        {
                            "type": "Action.OpenUrl",
                            "title": "Open Workspace",
                            "url": (
                                f"https://app.fabric.microsoft.com/groups/"
                                f"{run.workspace_id}/list?experience=fabric-developer"
                            ),
                        },
                    ],
                },
            }],
        }

    async def close(self):
        await self._http.aclose()
