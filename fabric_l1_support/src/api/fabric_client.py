"""Microsoft Fabric REST API client."""
import logging
from datetime import datetime
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models.schemas import PipelineRun, PipelineStatus

logger = logging.getLogger(__name__)


class FabricClient:
    """Client for Microsoft Fabric REST API."""

    BASE_URL = "https://api.fabric.microsoft.com/v1"

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _get_token(self) -> str:
        """Fetch AAD token, refresh if expired."""
        now = datetime.utcnow()
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        logger.info("Fetching AAD token from Azure...")
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://api.fabric.microsoft.com/.default",
        }
        resp = await self._http.post(url, data=payload)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Set expiry with 5 min buffer
        self._token_expiry = datetime.utcfromtimestamp(
            datetime.utcnow().timestamp() + data["expires_in"] - 300
        )
        return self._token

    async def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {await self._get_token()}",
            "Content-Type": "application/json",
        }

    def get_workspace_url(self, workspace_id: str, pipeline_id: str = "") -> str:
        """Build Fabric portal URL for a pipeline in this workspace."""
        base = f"https://app.fabric.microsoft.com/groups/{workspace_id}"
        if pipeline_id:
            return f"{base}/datapipelines/{pipeline_id}?experience=fabric-developer"
        return f"{base}/list?experience=fabric-developer"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def get_failed_pipeline_runs(
        self, workspace_id: str, lookback_minutes: int = 60
    ) -> list[PipelineRun]:
        """Fetch all failed pipeline runs in the last N minutes."""
        url = f"{self.BASE_URL}/workspaces/{workspace_id}/items"
        resp = await self._http.get(url, headers=await self._headers())
        resp.raise_for_status()

        pipelines = [
            item for item in resp.json().get("value", [])
            if item.get("type") == "DataPipeline"
        ]

        failed_runs = []
        for pipeline in pipelines:
            pipeline_name = pipeline.get("displayName", pipeline["id"])
            runs = await self.get_pipeline_runs(workspace_id, pipeline["id"], pipeline_name)
            failed_runs.extend([r for r in runs if r.status == PipelineStatus.FAILED])

        return failed_runs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def get_pipeline_runs(
        self, workspace_id: str, pipeline_id: str, pipeline_name: str = ""
    ) -> list[PipelineRun]:
        """Get recent runs for a specific pipeline."""
        url = f"{self.BASE_URL}/workspaces/{workspace_id}/dataPipelines/{pipeline_id}/jobs/instances"
        logger.info(f"Fetching runs for pipeline {pipeline_id}...")
        resp = await self._http.get(url, headers=await self._headers())

        if resp.status_code == 404:
            logger.warning(f"No runs found for pipeline {pipeline_id}")
            return []

        if resp.status_code != 200:
            logger.error(f"Failed to get runs: {resp.status_code} {resp.text}")
            return []

        runs = []
        for run in resp.json().get("value", []):
            try:
                status_val = run.get("status", "Unknown")
                # Map Fabric job status to our PipelineStatus
                status_map = {
                    "Failed": PipelineStatus.FAILED,
                    "Succeeded": PipelineStatus.SUCCEEDED,
                    "Running": PipelineStatus.RUNNING,
                    "Cancelled": PipelineStatus.CANCELLED,
                    "Canceled": PipelineStatus.CANCELLED,
                }
                status = status_map.get(status_val, PipelineStatus.FAILED)

                runs.append(PipelineRun(
                    pipeline_id=pipeline_id,
                    pipeline_name=pipeline_name or run.get("id", "Unknown"),
                    run_id=run.get("id", run.get("runId", "unknown")),
                    workspace_id=workspace_id,
                    status=status,
                    start_time=datetime.fromisoformat(
                        run["startTimeUtc"].replace("Z", "+00:00")
                    ) if run.get("startTimeUtc") else datetime.utcnow(),
                    end_time=datetime.fromisoformat(
                        run["endTimeUtc"].replace("Z", "+00:00")
                    ) if run.get("endTimeUtc") else None,
                    error_message=run.get("failureReason", run.get("errorMessage")),
                    error_code=run.get("errorCode"),
                ))
            except Exception as e:
                logger.error(f"Error parsing run {run}: {e}")
                continue

        logger.info(f"Pipeline {pipeline_id}: {len(runs)} runs found, "
                    f"{sum(1 for r in runs if r.status == PipelineStatus.FAILED)} failed")
        return runs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def get_run_logs(self, workspace_id: str, pipeline_id: str, run_id: str) -> str:
        """Fetch detailed logs for a pipeline run."""
        url = (
            f"{self.BASE_URL}/workspaces/{workspace_id}"
            f"/dataPipelines/{pipeline_id}/runs/{run_id}/logs"
        )
        resp = await self._http.get(url, headers=await self._headers())
        if resp.status_code == 404:
            return "No detailed logs available."
        resp.raise_for_status()
        return resp.text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def rerun_pipeline(
        self, workspace_id: str, pipeline_id: str
    ) -> Optional[str]:
        """Trigger a new pipeline run. Returns new run_id on success."""
        url = (
            f"{self.BASE_URL}/workspaces/{workspace_id}"
            f"/dataPipelines/{pipeline_id}/jobs/instances?jobType=Pipeline"
        )
        resp = await self._http.post(url, headers=await self._headers(), json={})
        if resp.status_code in (200, 202):
            location = resp.headers.get("Location", "")
            new_run_id = location.split("/")[-1] if location else None
            logger.info(f"Pipeline {pipeline_id} rerun triggered. Run ID: {new_run_id}")
            return new_run_id
        logger.error(f"Failed to rerun pipeline {pipeline_id}: {resp.status_code} {resp.text}")
        return None

    async def close(self):
        await self._http.aclose()
