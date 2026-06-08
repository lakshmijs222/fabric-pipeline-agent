"""
Create a flaky (network-failing) Data Pipeline in Microsoft Fabric via REST API.

The pipeline has a single Web activity that calls a random-status endpoint:
    https://httpstat.us/random/200,200,200,503,504
-> 60% returns 200 (succeeds), 40% returns 503/504 (fails like a network outage).

So the L1 bot can detect the failure, diagnose it as transient, and rerun it.

Usage:
    python create_fabric_pipeline.py
    python create_fabric_pipeline.py --name My_Test_Pipeline --run 5
"""
import argparse
import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("create_pipeline")

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FLAKY_URL = "https://httpstat.us/random/200,200,200,503,504"


def build_pipeline_definition(web_url: str) -> dict:
    """Build the Fabric Data Pipeline content (pipeline-content.json)."""
    return {
        "properties": {
            "activities": [
                {
                    "name": "FlakyNetworkCall",
                    "type": "WebActivity",
                    "dependsOn": [],
                    "policy": {
                        "timeout": "0.00:02:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                    },
                    "typeProperties": {
                        "method": "GET",
                        "url": web_url,
                    },
                }
            ]
        }
    }


def encode_definition(definition: dict) -> str:
    raw = json.dumps(definition).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


async def get_token(settings: Settings, http: httpx.AsyncClient) -> str:
    url = f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "scope": "https://api.fabric.microsoft.com/.default",
    }
    resp = await http.post(url, data=payload)
    resp.raise_for_status()
    logger.info("Got AAD token.")
    return resp.json()["access_token"]


async def create_pipeline(
    settings: Settings, http: httpx.AsyncClient, token: str, name: str, web_url: str
) -> str:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    workspace_id = settings.workspace_ids[0]

    definition = build_pipeline_definition(web_url)
    body = {
        "displayName": name,
        "type": "DataPipeline",
        "definition": {
            "parts": [
                {
                    "path": "pipeline-content.json",
                    "payload": encode_definition(definition),
                    "payloadType": "InlineBase64",
                }
            ]
        },
    }

    url = f"{FABRIC_API}/workspaces/{workspace_id}/items"
    logger.info(f"Creating pipeline '{name}' in workspace {workspace_id}...")
    resp = await http.post(url, headers=headers, json=body)

    # 201 = created immediately, 202 = accepted (async LRO)
    if resp.status_code == 201:
        item = resp.json()
        pid = item["id"]
        logger.info(f"✅ Pipeline created. ID: {pid}")
        return pid
    elif resp.status_code == 202:
        # Long-running op: poll the operation location
        op_url = resp.headers.get("Location")
        logger.info("Pipeline creation accepted (async). Polling for completion...")
        return await _poll_create(http, headers, op_url)
    else:
        logger.error(f"❌ Create failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()


async def _poll_create(http, headers, op_url) -> str:
    for _ in range(30):
        await asyncio.sleep(3)
        r = await http.get(op_url, headers=headers)
        data = r.json()
        status = data.get("status", "")
        logger.info(f"  ...operation status: {status}")
        if status == "Succeeded":
            # Fetch the result
            result_url = op_url.rstrip("/") + "/result"
            rr = await http.get(result_url, headers=headers)
            pid = rr.json().get("id")
            logger.info(f"✅ Pipeline created. ID: {pid}")
            return pid
        if status == "Failed":
            raise RuntimeError(f"Pipeline creation failed: {data}")
    raise TimeoutError("Pipeline creation did not complete in time.")


async def run_pipeline(
    settings: Settings, http: httpx.AsyncClient, token: str, pipeline_id: str
) -> str | None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    workspace_id = settings.workspace_ids[0]
    url = (
        f"{FABRIC_API}/workspaces/{workspace_id}/items/{pipeline_id}"
        f"/jobs/instances?jobType=Pipeline"
    )
    resp = await http.post(url, headers=headers, json={})
    if resp.status_code in (200, 202):
        loc = resp.headers.get("Location", "")
        run_id = loc.rstrip("/").split("/")[-1] if loc else "?"
        logger.info(f"  ▶ Run triggered. Run ID: {run_id}")
        return run_id
    logger.error(f"  ❌ Run failed: {resp.status_code} {resp.text}")
    return None


async def main(name: str, web_url: str, run_count: int):
    settings = Settings()
    async with httpx.AsyncClient(timeout=60.0) as http:
        token = await get_token(settings, http)
        pipeline_id = await create_pipeline(settings, http, token, name, web_url)

        ws = settings.workspace_ids[0]
        portal = (
            f"https://app.fabric.microsoft.com/groups/{ws}"
            f"/datapipelines/{pipeline_id}?experience=fabric-developer"
        )

        if run_count > 0:
            logger.info(f"Triggering {run_count} run(s) to generate failures...")
            for i in range(run_count):
                logger.info(f"Run {i+1}/{run_count}:")
                await run_pipeline(settings, http, token, pipeline_id)
                await asyncio.sleep(2)

        print("\n" + "=" * 60)
        print("  PIPELINE READY")
        print("=" * 60)
        print(f"  Name        : {name}")
        print(f"  Pipeline ID : {pipeline_id}")
        print(f"  Workspace   : {ws}")
        print(f"  Flaky URL   : {web_url}")
        print(f"  Open in portal:\n  {portal}")
        print("=" * 60)
        print("\n  Next: run  .\\start.bat  and watch the bot fix the failed runs.")
        print("  (Some runs will fail with 503/504 — that's the point.)\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a flaky test pipeline in Fabric")
    parser.add_argument("--name", default="Network_Flaky_Test", help="Pipeline display name")
    parser.add_argument("--url", default=FLAKY_URL, help="Web activity URL")
    parser.add_argument("--run", type=int, default=5, help="How many times to run it after creating (0 = don't run)")
    args = parser.parse_args()

    asyncio.run(main(args.name, args.url, args.run))
