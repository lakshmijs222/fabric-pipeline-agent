"""Entry point for Fabric L1 Support Bot."""
import asyncio
import logging
import logging.config
from pathlib import Path

from dotenv import load_dotenv

# Load .env file before anything else
load_dotenv(Path(__file__).parent / ".env")

from config.settings import Settings
from src.agent.auto_healer import AutoHealer
from src.agent.diagnoser import PipelineDiagnoser
from src.agent.l1_bot import L1SupportBot
from src.api.fabric_client import FabricClient
from src.notifications.teams_notifier import TeamsNotifier
from src.rag.knowledge_base import KnowledgeBase

LOGGING_CONFIG = {
    "version": 1,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/bot.log",
            "maxBytes": 10_485_760,  # 10 MB
            "backupCount": 5,
            "formatter": "standard",
        },
    },
    "root": {"level": "INFO", "handlers": ["console", "file"]},
}


async def main():
    import os
    os.makedirs("logs", exist_ok=True)

    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger("main")

    settings = Settings()

    logger.info("Initializing Fabric L1 Support Bot...")

    # Build knowledge base and index runbooks
    logger.info("Loading knowledge base...")
    kb = KnowledgeBase(db_path=settings.chroma_db_path)
    indexed = kb.index_runbooks(settings.runbooks_dir)
    logger.info(f"Knowledge base ready with {indexed} documents")

    # Build Fabric client
    logger.info("Connecting to Microsoft Fabric...")
    fabric = FabricClient(
        tenant_id=settings.tenant_id,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
    )

    # Build Claude diagnoser
    logger.info("Setting up Claude AI diagnoser...")
    diagnoser = PipelineDiagnoser(
        api_key=settings.anthropic_api_key,
        knowledge_base=kb,
    )

    retry_tracker: dict = {}
    healer = AutoHealer(
        fabric_client=fabric,
        knowledge_base=kb,
        retry_tracker=retry_tracker,
    )

    # Teams is optional — skip if webhook not configured
    teams_url = settings.teams_webhook_url
    if not teams_url or "your-org" in teams_url:
        logger.warning("Teams webhook not configured — alerts will be logged only.")
        teams_url = None
    notifier = TeamsNotifier(webhook_url=teams_url or "http://localhost")

    logger.info("All components ready. Starting bot...")

    bot = L1SupportBot(
        fabric_client=fabric,
        diagnoser=diagnoser,
        healer=healer,
        notifier=notifier,
        workspace_ids=settings.workspace_ids,
        poll_interval_seconds=settings.poll_interval_seconds,
        audit_log_path=settings.audit_log_path,
    )

    try:
        await bot.run()
    finally:
        await fabric.close()
        await notifier.close()
        logger.info("Bot shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
