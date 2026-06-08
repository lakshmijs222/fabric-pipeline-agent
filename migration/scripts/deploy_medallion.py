"""
Create Bronze/Silver/Gold notebooks in Fabric and chain them into the
migration pipeline (after the Copy step).

Layers (all in SQL_Migration_LH, prefixed Delta tables):
    Files/Raw/...           -> nb_bronze -> Tables/bronze_<table>
    bronze_<table>          -> nb_silver -> Tables/silver_<table>
    silver_<table>          -> nb_gold   -> Tables/gold_dim_*, gold_fact_*

Usage:
    python deploy_medallion.py --user
"""
import argparse
import asyncio
import base64
import json
import logging
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse auth + builders from the migration deploy script
from deploy_migration_pipeline import (  # noqa: E402
    FABRIC_API,
    LAKEHOUSE_ID,
    MIGRATION_FOLDER_ID,
    PIPELINE_NAME,
    Settings,
    build_pipeline_definition,
    encode_definition,
    get_token,
    get_user_token_devicecode,
    update_definition,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("deploy_medallion")

LAKEHOUSE_NAME = "SQL_Migration_LH"
MIGRATION_PIPELINE_ID = "37f997c7-f45a-4f0d-80cc-bf710ddaf265"

# ── Notebook source code (PySpark) ─────────────────────────────────────────────

BRONZE_CODE = r'''# Bronze layer: ingest raw Parquet files -> Delta tables (bronze_<table>)
from notebookutils import mssparkutils
from pyspark.sql.functions import current_timestamp, input_file_name

RAW_BASE = "Files/Raw"

tables = [f.name.rstrip("/") for f in mssparkutils.fs.ls(RAW_BASE)]
print("Found raw subjects:", tables)

for t in tables:
    try:
        # Read every parquet under Raw/<table>/<yyyy>/<MM>/<dd>/
        df = (spark.read.parquet(f"{RAW_BASE}/{t}/*/*/*/*.parquet")
              .withColumn("_ingested_at", current_timestamp())
              .withColumn("_source_file", input_file_name()))
        tbl = f"bronze_{t.lower()}"
        (df.write.format("delta").mode("overwrite")
           .option("overwriteSchema", "true").saveAsTable(tbl))
        print(f"  OK  {tbl}: {df.count()} rows")
    except Exception as e:
        print(f"  SKIP {t}: {e}")

print("Bronze layer complete.")
'''

SILVER_CODE = r'''# Silver layer: clean bronze tables -> silver_<table>
from pyspark.sql.functions import col, trim

bronze_tables = [t.name for t in spark.catalog.listTables() if t.name.startswith("bronze_")]
print("Bronze tables:", bronze_tables)

for bt in bronze_tables:
    try:
        df = spark.table(bt)
        # Drop bronze technical columns for the clean layer
        for tech in ["_ingested_at", "_source_file"]:
            if tech in df.columns:
                df = df.drop(tech)
        # Trim all string columns
        for c, dt in df.dtypes:
            if dt == "string":
                df = df.withColumn(c, trim(col(c)))
        # Remove exact duplicates and fully-empty rows
        df = df.dropDuplicates().na.drop(how="all")
        st = bt.replace("bronze_", "silver_")
        (df.write.format("delta").mode("overwrite")
           .option("overwriteSchema", "true").saveAsTable(st))
        print(f"  OK  {st}: {df.count()} rows")
    except Exception as e:
        print(f"  SKIP {bt}: {e}")

print("Silver layer complete.")
'''

GOLD_CODE = r'''# Gold layer: curated dimensional tables from silver
from pyspark.sql.functions import col

def t(name):
    """Return silver table if it exists, else None."""
    try:
        return spark.table(name)
    except Exception:
        print(f"  (missing) {name}")
        return None

def save(df, name):
    (df.write.format("delta").mode("overwrite")
       .option("overwriteSchema", "true").saveAsTable(name))
    print(f"  OK  {name}: {df.count()} rows")

# ---- DimCustomer ----
cust = t("silver_customer")
if cust is not None:
    cols = [c for c in ["CustomerID","Title","FirstName","MiddleName","LastName",
                        "CompanyName","SalesPerson","EmailAddress","Phone"] if c in cust.columns]
    save(cust.select(*cols).dropDuplicates(["CustomerID"]), "gold_dim_customer")

# ---- DimProduct (+ category name) ----
prod = t("silver_product")
cat  = t("silver_productcategory")
if prod is not None:
    dim = prod
    if cat is not None and "ProductCategoryID" in prod.columns and "ProductCategoryID" in cat.columns:
        dim = prod.join(cat.select(col("ProductCategoryID"),
                                   col("Name").alias("CategoryName")),
                        on="ProductCategoryID", how="left")
    keep = [c for c in ["ProductID","Name","ProductNumber","Color","StandardCost",
                        "ListPrice","Size","Weight","CategoryName"] if c in dim.columns]
    save(dim.select(*keep).dropDuplicates(["ProductID"]), "gold_dim_product")

# ---- FactSalesOrder (header + detail) ----
hdr = t("silver_salesorderheader")
det = t("silver_salesorderdetail")
if hdr is not None and det is not None and "SalesOrderID" in hdr.columns and "SalesOrderID" in det.columns:
    hsel = [c for c in ["SalesOrderID","OrderDate","DueDate","ShipDate","CustomerID",
                        "SubTotal","TaxAmt","Freight","TotalDue"] if c in hdr.columns]
    dsel = [c for c in ["SalesOrderID","SalesOrderDetailID","ProductID","OrderQty",
                        "UnitPrice","UnitPriceDiscount","LineTotal"] if c in det.columns]
    fact = det.select(*dsel).join(hdr.select(*hsel), on="SalesOrderID", how="inner")
    save(fact, "gold_fact_salesorder")

print("Gold layer complete.")
'''


def build_notebook_ipynb(code: str, workspace_id: str) -> str:
    """Wrap PySpark code into a Fabric notebook (.ipynb) with default lakehouse."""
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {
                "cell_type": "code",
                # Fabric requires source as a list of lines (each keeping its newline)
                "source": code.splitlines(keepends=True),
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }
        ],
        "metadata": {
            "language_info": {"name": "python"},
            "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"},
            "microsoft": {"language": "python"},
            "dependencies": {
                "lakehouse": {
                    "default_lakehouse": LAKEHOUSE_ID,
                    "default_lakehouse_name": LAKEHOUSE_NAME,
                    "default_lakehouse_workspace_id": workspace_id,
                }
            },
        },
    }
    return base64.b64encode(json.dumps(nb).encode("utf-8")).decode("utf-8")


async def create_notebook(http, headers, ws, name, code, workspace_id) -> str:
    body = {
        "displayName": name,
        "type": "Notebook",
        "folderId": MIGRATION_FOLDER_ID,
        "definition": {
            "format": "ipynb",
            "parts": [
                {
                    "path": "notebook-content.ipynb",
                    "payload": build_notebook_ipynb(code, workspace_id),
                    "payloadType": "InlineBase64",
                }
            ],
        },
    }
    url = f"{FABRIC_API}/workspaces/{ws}/items"
    logger.info(f"Creating notebook '{name}'...")
    resp = await http.post(url, headers=headers, json=body)
    if resp.status_code == 201:
        nid = resp.json()["id"]
    elif resp.status_code == 202:
        op = resp.headers.get("Location")
        nid = None
        for _ in range(40):
            await asyncio.sleep(3)
            r = await http.get(op, headers=headers)
            st = r.json().get("status", "")
            logger.info(f"  ...{name} status: {st}")
            if st == "Succeeded":
                rr = await http.get(op.rstrip("/") + "/result", headers=headers)
                nid = rr.json().get("id")
                break
            if st == "Failed":
                raise RuntimeError(f"Notebook create failed: {r.json()}")
        if not nid:
            raise TimeoutError(f"Notebook {name} creation timed out.")
    else:
        logger.error(f"Notebook create failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    logger.info(f"  ✅ {name}: {nid}")
    return nid


def add_notebook_activities(definition: dict, ws: str, bronze_id, silver_id, gold_id) -> dict:
    """Append Bronze->Silver->Gold notebook activities, chained after ForEachTable."""
    def nb_activity(name, notebook_id, depends_on):
        return {
            "name": name,
            "type": "TridentNotebook",
            "dependsOn": [
                {"activity": depends_on, "dependencyConditions": ["Succeeded"]}
            ],
            "policy": {"timeout": "0.06:00:00", "retry": 1},
            "typeProperties": {
                "notebookId": notebook_id,
                "workspaceId": ws,
            },
        }

    acts = definition["properties"]["activities"]
    acts.append(nb_activity("RunBronze", bronze_id, "ForEachTable"))
    acts.append(nb_activity("RunSilver", silver_id, "RunBronze"))
    acts.append(nb_activity("RunGold", gold_id, "RunSilver"))
    return definition


async def main(connection_id: str, schema_filter: str, as_user: bool):
    settings = Settings()
    ws = settings.workspace_ids[0]

    async with httpx.AsyncClient(timeout=120.0) as http:
        token = await (get_user_token_devicecode(settings, http) if as_user else get_token(settings, http))
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1. Create the 3 notebooks
        bronze_id = await create_notebook(http, headers, ws, "nb_bronze", BRONZE_CODE, ws)
        silver_id = await create_notebook(http, headers, ws, "nb_silver", SILVER_CODE, ws)
        gold_id = await create_notebook(http, headers, ws, "nb_gold", GOLD_CODE, ws)

        # 2. Rebuild pipeline definition (Copy + chained notebooks) and update in place
        definition = build_pipeline_definition(connection_id, LAKEHOUSE_ID, ws, schema_filter)
        definition = add_notebook_activities(definition, ws, bronze_id, silver_id, gold_id)
        await update_definition(settings, http, token, MIGRATION_PIPELINE_ID, definition)

        portal = f"https://app.fabric.microsoft.com/groups/{ws}/datapipelines/{MIGRATION_PIPELINE_ID}?experience=fabric-developer"
        print("\n" + "=" * 60)
        print("  MEDALLION DEPLOYED")
        print("=" * 60)
        print(f"  Notebooks : nb_bronze={bronze_id}")
        print(f"              nb_silver={silver_id}")
        print(f"              nb_gold={gold_id}")
        print(f"  Pipeline  : {PIPELINE_NAME} ({MIGRATION_PIPELINE_ID})")
        print(f"  Flow      : Lookup -> ForEach(Copy) -> Bronze -> Silver -> Gold")
        print(f"  Open: {portal}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy medallion notebooks + chain into pipeline")
    parser.add_argument("--connection-id", default="d37f6c40-37a0-448f-a009-9561dd55455f")
    parser.add_argument("--schema", default="SalesLT")
    parser.add_argument("--user", action="store_true", help="Sign in interactively")
    args = parser.parse_args()
    asyncio.run(main(args.connection_id, args.schema, args.user))
