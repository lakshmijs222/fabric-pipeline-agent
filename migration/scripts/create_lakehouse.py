"""
Create a Lakehouse in Microsoft Fabric via REST API.

Usage:
    python create_lakehouse.py
    python create_lakehouse.py --name SQL_Migration_LH
"""
import argparse
import asyncio
import logging
from pathlib import Path

import sys

import httpx
from dotenv import load_dotenv

# Project root is the parent of this Migration folder
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("create_lakehouse")

FABRIC_API = "https://api.fabric.microsoft.com/v1"


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


async def create_lakehouse(settings, http, token, name) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ws = settings.workspace_ids[0]
    url = f"{FABRIC_API}/workspaces/{ws}/lakehouses"
    body = {"displayName": name, "description": "Lakehouse for SQL Server -> Fabric migration"}

    logger.info(f"Creating Lakehouse '{name}' in workspace {ws}...")
    resp = await http.post(url, headers=headers, json=body)

    if resp.status_code == 201:
        return resp.json()
    elif resp.status_code == 202:
        op_url = resp.headers.get("Location")
        logger.info("Creation accepted (async). Polling...")
        for _ in range(30):
            await asyncio.sleep(3)
            r = await http.get(op_url, headers=headers)
            status = r.json().get("status", "")
            logger.info(f"  ...status: {status}")
            if status == "Succeeded":
                rr = await http.get(op_url.rstrip("/") + "/result", headers=headers)
                return rr.json()
            if status == "Failed":
                raise RuntimeError(f"Creation failed: {r.json()}")
        raise TimeoutError("Lakehouse creation timed out.")
    else:
        logger.error(f"Create failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()


async def main(name: str):
    settings = Settings()
    ws = settings.workspace_ids[0]
    async with httpx.AsyncClient(timeout=60.0) as http:
        token = await get_token(settings, http)
        lh = await create_lakehouse(settings, http, token, name)

        lh_id = lh.get("id")
        portal = f"https://app.fabric.microsoft.com/groups/{ws}/lakehouses/{lh_id}"
        print("\n" + "=" * 60)
        print("  LAKEHOUSE CREATED")
        print("=" * 60)
        print(f"  Name         : {lh.get('displayName', name)}")
        print(f"  Lakehouse ID : {lh_id}")
        print(f"  Workspace    : {ws}")
        print(f"  Open in portal:\n  {portal}")
        print("=" * 60)
        # Print OneLake paths for reference
        print(f"\n  OneLake Files path:")
        print(f"  abfss://{ws}@onelake.dfs.fabric.microsoft.com/{lh_id}/Files/")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a Fabric Lakehouse")
    parser.add_argument("--name", default="SQL_Migration_LH", help="Lakehouse display name")
    args = parser.parse_args()
    asyncio.run(main(args.name))
