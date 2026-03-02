"""DailyMe Scheduler — run pipeline on a loop + periodic cleanup.

Usage:
    python scripts/scheduler.py              # default: every 2 minutes
    python scripts/scheduler.py --interval 300  # every 5 minutes

Runs as a long-lived process. Designed for:
  - Local dev: run in a terminal
  - Production: run as a background process or systemd service
  - OpenHands agent: execute and leave running
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dailyme.scheduler")

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    logger.info("Received %s — shutting down after current run", signal.Signals(sig).name)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


async def run_once():
    """Run the pipeline once, with error handling."""
    from scripts.run_pipeline import run_pipeline

    try:
        stats = await run_pipeline()
        return stats
    except Exception:
        logger.exception("Pipeline run failed")
        return None


async def cleanup():
    """Delete expired stories via the cleanup endpoint logic."""
    from datetime import timedelta
    from sqlalchemy import delete, select
    from app.db import async_session
    from app.models import Feedback, StoryGroup, StoryGroupMember

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with async_session() as session:
        expired = await session.execute(
            select(StoryGroup.id).where(
                StoryGroup.first_seen_at < cutoff,
                StoryGroup.starred == False,
            )
        )
        expired_ids = [r[0] for r in expired.all()]

        if expired_ids:
            await session.execute(
                delete(StoryGroupMember).where(StoryGroupMember.story_group_id.in_(expired_ids))
            )
            await session.execute(
                delete(Feedback).where(Feedback.story_group_id.in_(expired_ids))
            )
            await session.execute(
                delete(StoryGroup).where(StoryGroup.id.in_(expired_ids))
            )
            await session.commit()
            logger.info("Cleaned up %d expired story groups", len(expired_ids))


async def main(interval_seconds: int):
    logger.info("DailyMe Scheduler started — polling every %ds", interval_seconds)
    run_count = 0

    while not _shutdown:
        run_count += 1
        logger.info("--- Run #%d at %s ---", run_count, datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))

        await run_once()

        # Cleanup expired stories every 10 runs
        if run_count % 10 == 0:
            await cleanup()

        if _shutdown:
            break

        logger.info("Sleeping %ds until next run...", interval_seconds)
        # Sleep in small increments so we can respond to shutdown quickly
        for _ in range(interval_seconds):
            if _shutdown:
                break
            await asyncio.sleep(1)

    logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DailyMe pipeline scheduler")
    parser.add_argument("--interval", type=int, default=120, help="Seconds between runs (default: 120)")
    args = parser.parse_args()
    asyncio.run(main(args.interval))
