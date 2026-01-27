"""
Daily scheduler for incremental ThetaData option updates
Runs daily to download new data without re-fetching existing data
"""
import logging
from datetime import datetime, time
from apscheduler.schedulers.blocking import BlockingScheduler
from pathlib import Path

from config import Config
from daemon_manager import DaemonManager
from downloader import OptionDownloader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Path.home() / "data" / "thetadata" / "scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def daily_update():
    """Run daily update job"""
    logger.info("=" * 70)
    logger.info("STARTING DAILY OPTION DATA UPDATE")
    logger.info("=" * 70)

    try:
        config = Config()
        daemon_manager = DaemonManager(config)
        downloader = OptionDownloader()

        # Step 1: Ensure daemon is running
        if not daemon_manager.ensure_running():
            logger.error("Failed to ensure daemon is running")
            return False

        # Step 2: Download new data
        # The downloader will use last update times to only fetch new data
        success = downloader.download_all_options()

        if success:
            logger.info("✓ Daily update completed successfully")
        else:
            logger.warning("⚠ Daily update completed with issues")

        return success

    except Exception as e:
        logger.error(f"✗ Daily update failed: {e}", exc_info=True)
        return False
    finally:
        logger.info("=" * 70)


def main():
    """Setup and run scheduler"""
    logger.info("ThetaData Option Downloader - Daily Scheduler Starting")
    logger.info(f"Logging to: {Path.home() / 'data' / 'thetadata' / 'scheduler.log'}")

    # Create scheduler
    scheduler = BlockingScheduler()

    # Schedule daily update at 2:00 AM
    scheduler.add_job(
        daily_update,
        'cron',
        hour=2,
        minute=0,
        id='daily_option_update',
        name='Daily ThetaData Option Update',
        misfire_grace_time=3600  # Allow 1 hour grace period
    )

    logger.info("Scheduler configured:")
    logger.info("  Job: Daily ThetaData Option Update")
    logger.info("  Time: 2:00 AM daily")
    logger.info("  Data directory: ~/data/thetadata/")
    logger.info("  Logs: ~/data/thetadata/scheduler.log")
    logger.info("\nStarting scheduler (CTRL+C to stop)...")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
