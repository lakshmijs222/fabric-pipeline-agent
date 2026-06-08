"""
Deploy a metadata-driven SQL Server -> Lakehouse migration pipeline in Fabric.

Design (single Copy activity, fully dynamic):
    Lookup (get table list)  ->  ForEach table  ->  Copy (SQL -> Lakehouse Parquet)

Sink layout:
    Files/Raw/<Table>/<yyyy>/<MM>/<dd>/<Table>_<yyyy-MM-dd>.parquet

Usage:
    python deploy_migration_pipeline.py --connection-id <GUID>
    python deploy_migration_pipeline.py --connection-id <GUID> --schema SalesLT
"""
import argparse
import asyncio
import base64
import json
import logging
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("deploy_migration")

FABRIC_API = "https://api.fabric.microsoft.com/v1"

# The migration Lakehouse we created earlier
LAKEHOUSE_ID = "17cdbdae-6b12-4974-a61e-393642bcc8f0"
PIPELINE_NAME = "SQL_to_Lakehouse_Migration"
MIGRATION_FOLDER_ID = "f078868f-e4bb-44c0-9d8c-4ac20847a523"  # Fabric 'Migration' folder
SOURCE_DATABASE = "AdventureWorksLT2022"


def build_pipeline_definition(connection_id: str, lakehouse_id: str, workspace_id: str, schema_filter: str) -> dict:
    """Metadata-driven pipeline: Lookup -> ForEach -> single Copy."""

    # WHERE clause: optionally restrict to one schema
    where = "WHERE TABLE_TYPE = 'BASE TABLE'"
    if schema_filter:
        where += f" AND TABLE_SCHEMA = '{schema_filter}'"
    table_list_query = (
        "SELECT TABLE_SCHEMA, TABLE_NAME "
        f"FROM INFORMATION_SCHEMA.TABLES {where}"
    )

    # Dynamic sink path expressions (evaluated at run time)
    folder_path = (
        "@concat(pipeline().parameters.RootFolder, '/', item().TABLE_NAME, '/', "
        "formatDateTime(utcnow(),'yyyy'), '/', "
        "formatDateTime(utcnow(),'MM'), '/', "
        "formatDateTime(utcnow(),'dd'))"
    )
    file_name = (
        "@concat(item().TABLE_NAME, '_', "
        "formatDateTime(utcnow(),'yyyy-MM-dd'), '.parquet')"
    )
    source_query = (
        "@concat('SELECT * FROM [', item().TABLE_SCHEMA, '].[', item().TABLE_NAME, ']')"
    )

    # SQL source dataset settings — connection + database are BOTH required for the
    # connection to bind in the Fabric UI/runtime.
    def sql_dataset_settings():
        return {
            "annotations": [],
            "type": "SqlServerTable",
            "schema": [],
            "typeProperties": {
                "database": SOURCE_DATABASE,
            },
            "externalReferences": {"connection": connection_id},
        }

    lakehouse_linked = {
        "name": "MigrationLakehouse",
        "properties": {
            "type": "Lakehouse",
            "typeProperties": {
                "workspaceId": workspace_id,
                "artifactId": lakehouse_id,
                "rootFolder": "Files",
            },
        },
    }

    return {
        "properties": {
            "parameters": {
                "RootFolder": {"type": "string", "defaultValue": "Raw"},
            },
            "activities": [
                {
                    "name": "GetTableList",
                    "type": "Lookup",
                    "dependsOn": [],
                    "policy": {"timeout": "0.00:10:00", "retry": 1},
                    "typeProperties": {
                        "source": {
                            "type": "SqlServerSource",
                            "sqlReaderQuery": table_list_query,
                            "datasetSettings": sql_dataset_settings(),
                        },
                        "firstRowOnly": False,
                    },
                },
                {
                    "name": "ForEachTable",
                    "type": "ForEach",
                    "dependsOn": [
                        {"activity": "GetTableList", "dependencyConditions": ["Succeeded"]}
                    ],
                    "typeProperties": {
                        "items": {
                            "value": "@activity('GetTableList').output.value",
                            "type": "Expression",
                        },
                        "isSequential": False,
                        "batchCount": 4,
                        "activities": [
                            {
                                "name": "CopyTable",
                                "type": "Copy",
                                "dependsOn": [],
                                "policy": {"timeout": "0.12:00:00", "retry": 2,
                                           "retryIntervalInSeconds": 30},
                                "typeProperties": {
                                    "source": {
                                        "type": "SqlServerSource",
                                        "sqlReaderQuery": {
                                            "value": source_query,
                                            "type": "Expression",
                                        },
                                        "datasetSettings": sql_dataset_settings(),
                                    },
                                    "sink": {
                                        "type": "ParquetSink",
                                        "storeSettings": {"type": "LakehouseWriteSettings"},
                                        "formatSettings": {"type": "ParquetWriteSettings"},
                                        "datasetSettings": {
                                            "type": "Parquet",
                                            "typeProperties": {
                                                "location": {
                                                    "type": "LakehouseLocation",
                                                    "fileName": {
                                                        "value": file_name,
                                                        "type": "Expression",
                                                    },
                                                    "folderPath": {
                                                        "value": folder_path,
                                                        "type": "Expression",
                                                    },
                                                },
                                            },
                                            "linkedService": lakehouse_linked,
                                        },
                                    },
                                    "enableStaging": False,
                                },
                            }
                        ],
                    },
                },
            ],
        }
    }


def encode_definition(definition: dict) -> str:
    return base64.b64encode(json.dumps(definition).encode("utf-8")).decode("utf-8")


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
    logger.info("Got AAD token (service principal).")
    return resp.json()["access_token"]


# Azure CLI public client ID — supports device-code flow and is pre-authorized for Fabric
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


async def get_user_token_devicecode(settings, http) -> str:
    """Interactive sign-in: deploy as the logged-in user (owns connection + workspace)."""
    tenant = settings.tenant_id
    scope = "https://api.fabric.microsoft.com/.default offline_access"

    dc = await http.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
        data={"client_id": AZURE_CLI_CLIENT_ID, "scope": scope},
    )
    dc.raise_for_status()
    d = dc.json()

    print("\n" + "*" * 60)
    print("  SIGN IN TO DEPLOY AS YOURSELF")
    print("*" * 60)
    print(f"  1. Open: {d['verification_uri']}")
    print(f"  2. Enter code: {d['user_code']}")
    print(f"  3. Sign in with your Fabric account (LakshhmiChowdary)")
    print("*" * 60 + "\n")
    print("  Waiting for you to complete sign-in...")

    interval = int(d.get("interval", 5))
    for _ in range(int(d.get("expires_in", 900)) // interval):
        await asyncio.sleep(interval)
        tok = await http.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": AZURE_CLI_CLIENT_ID,
                "device_code": d["device_code"],
            },
        )
        body = tok.json()
        if tok.status_code == 200:
            logger.info("Signed in successfully (user token).")
            return body["access_token"]
        err = body.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise RuntimeError(f"Sign-in failed: {body}")
    raise TimeoutError("Sign-in timed out.")


async def deploy(settings, http, token, definition, name) -> str:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ws = settings.workspace_ids[0]
    body = {
        "displayName": name,
        "type": "DataPipeline",
        "folderId": MIGRATION_FOLDER_ID,
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
    url = f"{FABRIC_API}/workspaces/{ws}/items"
    logger.info(f"Deploying pipeline '{name}'...")
    resp = await http.post(url, headers=headers, json=body)

    if resp.status_code == 201:
        return resp.json()["id"]
    elif resp.status_code == 202:
        op = resp.headers.get("Location")
        logger.info("Accepted (async). Polling...")
        for _ in range(40):
            await asyncio.sleep(3)
            r = await http.get(op, headers=headers)
            status = r.json().get("status", "")
            logger.info(f"  ...status: {status}")
            if status == "Succeeded":
                rr = await http.get(op.rstrip("/") + "/result", headers=headers)
                return rr.json().get("id")
            if status == "Failed":
                raise RuntimeError(f"Deploy failed: {r.json()}")
        raise TimeoutError("Deploy timed out.")
    else:
        logger.error(f"Deploy failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()


async def update_definition(settings, http, token, pipeline_id, definition):
    """Overwrite an existing pipeline's definition (updateDefinition)."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ws = settings.workspace_ids[0]
    body = {
        "definition": {
            "parts": [
                {
                    "path": "pipeline-content.json",
                    "payload": encode_definition(definition),
                    "payloadType": "InlineBase64",
                }
            ]
        }
    }
    url = f"{FABRIC_API}/workspaces/{ws}/items/{pipeline_id}/updateDefinition"
    logger.info(f"Updating pipeline definition {pipeline_id}...")
    resp = await http.post(url, headers=headers, json=body)
    if resp.status_code in (200, 202):
        logger.info("✅ Pipeline definition updated.")
        return pipeline_id
    logger.error(f"Update failed: {resp.status_code} {resp.text}")
    resp.raise_for_status()


async def get_definition(settings, http, token, pipeline_id):
    """Fetch and print the current pipeline definition (diagnostic)."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ws = settings.workspace_ids[0]
    url = f"{FABRIC_API}/workspaces/{ws}/items/{pipeline_id}/getDefinition"
    resp = await http.post(url, headers=headers)
    if resp.status_code == 202:
        op = resp.headers.get("Location")
        for _ in range(20):
            await asyncio.sleep(2)
            r = await http.get(op, headers=headers)
            if r.json().get("status") == "Succeeded":
                resp = await http.get(op.rstrip("/") + "/result", headers=headers)
                break
    parts = resp.json().get("definition", {}).get("parts", [])
    for p in parts:
        if p["path"] == "pipeline-content.json":
            decoded = base64.b64decode(p["payload"]).decode("utf-8")
            print("\n----- CURRENT pipeline-content.json -----")
            print(json.dumps(json.loads(decoded), indent=2))
            print("----- END -----\n")


async def main(connection_id: str, schema_filter: str, run_now: bool, as_user: bool,
               update_id: str = None, dump_id: str = None):
    settings = Settings()
    ws = settings.workspace_ids[0]
    definition = build_pipeline_definition(connection_id, LAKEHOUSE_ID, ws, schema_filter)

    async with httpx.AsyncClient(timeout=90.0) as http:
        if as_user:
            token = await get_user_token_devicecode(settings, http)
        else:
            token = await get_token(settings, http)

        # Diagnostic: dump an existing pipeline's definition and exit
        if dump_id:
            await get_definition(settings, http, token, dump_id)
            return

        # Update existing pipeline in place
        if update_id:
            pid = await update_definition(settings, http, token, update_id, definition)
        else:
            pid = await deploy(settings, http, token, definition, PIPELINE_NAME)

        portal = f"https://app.fabric.microsoft.com/groups/{ws}/datapipelines/{pid}?experience=fabric-developer"
        print("\n" + "=" * 60)
        print("  MIGRATION PIPELINE DEPLOYED")
        print("=" * 60)
        print(f"  Name        : {PIPELINE_NAME}")
        print(f"  Pipeline ID : {pid}")
        print(f"  Schema      : {schema_filter or 'ALL schemas'}")
        print(f"  Connection  : {connection_id}")
        print(f"  Lakehouse   : {LAKEHOUSE_ID}")
        print(f"  Sink layout : Files/Raw/<Table>/<yyyy>/<MM>/<dd>/<Table>_<yyyy-MM-dd>.parquet")
        print(f"  Open: {portal}")
        print("=" * 60 + "\n")

        if run_now:
            url = f"{FABRIC_API}/workspaces/{ws}/items/{pid}/jobs/instances?jobType=Pipeline"
            r = await http.post(url, headers={"Authorization": f"Bearer {token}"}, json={})
            logger.info(f"Triggered run: {r.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy SQL->Lakehouse migration pipeline")
    parser.add_argument("--connection-id", required=True, help="Fabric SQL Server connection ID")
    parser.add_argument("--schema", default="SalesLT", help="Schema filter (empty = all schemas)")
    parser.add_argument("--run", action="store_true", help="Trigger a run after deploy")
    parser.add_argument("--user", action="store_true", help="Sign in interactively and deploy as yourself")
    parser.add_argument("--update", default=None, help="Update an existing pipeline ID in place")
    parser.add_argument("--dump", default=None, help="Dump an existing pipeline's definition and exit")
    args = parser.parse_args()
    asyncio.run(main(args.connection_id, args.schema, args.run, args.user, args.update, args.dump))
