"""
Create a 'Migration' folder in the Fabric workspace and move migration items into it.

Usage:
    python organize_workspace.py
    python organize_workspace.py --folder Migration --move 17cdbdae-6b12-4974-a61e-393642bcc8f0
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
logger = logging.getLogger("organize")

FABRIC_API = "https://api.fabric.microsoft.com/v1"

# Items considered part of the migration (move these). Lakehouse created earlier:
MIGRATION_ITEM_IDS = [
    "17cdbdae-6b12-4974-a61e-393642bcc8f0",  # SQL_Migration_LH
]


async def get_token(settings, http) -> str:
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


async def list_items(http, headers, ws) -> list[dict]:
    resp = await http.get(f"{FABRIC_API}/workspaces/{ws}/items", headers=headers)
    resp.raise_for_status()
    return resp.json().get("value", [])


async def get_or_create_folder(http, headers, ws, folder_name) -> str:
    # Check existing folders first
    resp = await http.get(f"{FABRIC_API}/workspaces/{ws}/folders", headers=headers)
    if resp.status_code == 200:
        for f in resp.json().get("value", []):
            if f.get("displayName") == folder_name:
                logger.info(f"Folder '{folder_name}' already exists. ID: {f['id']}")
                return f["id"]

    logger.info(f"Creating folder '{folder_name}'...")
    resp = await http.post(
        f"{FABRIC_API}/workspaces/{ws}/folders",
        headers=headers,
        json={"displayName": folder_name},
    )
    if resp.status_code in (200, 201):
        fid = resp.json()["id"]
        logger.info(f"Folder created. ID: {fid}")
        return fid
    logger.error(f"Folder create failed: {resp.status_code} {resp.text}")
    resp.raise_for_status()


async def move_item(http, headers, ws, item_id, folder_id) -> bool:
    url = f"{FABRIC_API}/workspaces/{ws}/items/{item_id}/move"
    resp = await http.post(url, headers=headers, json={"targetFolderId": folder_id})
    if resp.status_code in (200, 202):
        logger.info(f"  ✅ Moved item {item_id}")
        return True
    logger.error(f"  ❌ Move failed for {item_id}: {resp.status_code} {resp.text}")
    return False


async def main(folder_name: str, move_ids: list[str]):
    settings = Settings()
    ws = settings.workspace_ids[0]
    async with httpx.AsyncClient(timeout=60.0) as http:
        token = await get_token(settings, http)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Show what's in the workspace
        items = await list_items(http, headers, ws)
        logger.info(f"Workspace has {len(items)} items:")
        for it in items:
            logger.info(f"  - {it.get('displayName')} [{it.get('type')}] {it.get('id')}")

        folder_id = await get_or_create_folder(http, headers, ws, folder_name)

        logger.info(f"Moving {len(move_ids)} item(s) into '{folder_name}'...")
        moved = 0
        for item_id in move_ids:
            if await move_item(http, headers, ws, item_id, folder_id):
                moved += 1

        print("\n" + "=" * 60)
        print("  WORKSPACE ORGANIZED")
        print("=" * 60)
        print(f"  Folder    : {folder_name} ({folder_id})")
        print(f"  Items moved: {moved}/{len(move_ids)}")
        print(f"  Workspace : {ws}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organize Fabric workspace into folders")
    parser.add_argument("--folder", default="Migration", help="Folder name")
    parser.add_argument("--move", nargs="*", default=MIGRATION_ITEM_IDS,
                        help="Item IDs to move (default: migration items)")
    args = parser.parse_args()
    asyncio.run(main(args.folder, args.move))
