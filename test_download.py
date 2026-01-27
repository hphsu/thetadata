"""
Test script for ThetaData option downloader
Download small sample data to verify everything works before full download
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from config import Config
from thetadata_client import ThetaDataClient
from data_manager import ParquetDataManager
from daemon_manager import DaemonManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_daemon_connection():
    """Test if ThetaTerminal daemon is accessible, auto-start if needed"""
    logger.info("=" * 60)
    logger.info("TEST 1: ThetaTerminal Daemon Connection")
    logger.info("=" * 60)

    config = Config()
    daemon_manager = DaemonManager(config)

    # Check if already running
    if daemon_manager.is_daemon_running():
        logger.info("✓ ThetaTerminal daemon is running and accessible")
        logger.info(f"  Base URL: {config.theta_base_url}")
        return True

    # Try to start daemon
    logger.warning("ThetaTerminal daemon is not running")
    logger.info("Attempting to auto-start daemon...")

    if daemon_manager.ensure_running():
        logger.info("✓ ThetaTerminal daemon started successfully")
        logger.info(f"  Base URL: {config.theta_base_url}")
        return True
    else:
        logger.error("✗ Failed to start ThetaTerminal daemon")
        logger.error(f"  Expected at: {config.theta_base_url}")
        logger.error("  Please manually start: java -jar ThetaTerminalv3.jar")
        return False


def test_get_symbols():
    """Test retrieving symbol list"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Get Available Symbols")
    logger.info("=" * 60)

    config = Config()
    daemon_manager = DaemonManager(config)
    daemon_manager.is_daemon_running()  # This updates config with correct port

    client = ThetaDataClient(config)

    try:
        symbols = client.get_option_symbols()
        if symbols:
            logger.info(f"✓ Successfully retrieved option symbols")
            logger.info(f"  Found {len(symbols)} symbols")
            # Return only popular symbols we know have VALUE subscription
            popular = ["SPY", "QQQ", "IWM"]
            available = [s for s in popular if s in symbols]
            if not available:
                # Fallback to first few symbols
                available = symbols[:3]
            logger.info(f"  Testing with: {available}")
            return available
        else:
            logger.warning("⚠ No symbols returned")
            return []
    except Exception as e:
        logger.error(f"✗ Failed to get symbols: {e}")
        return []


def test_download_sample_data(symbols: list):
    """Test downloading sample data for a few symbols"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Download Sample Option Data")
    logger.info("=" * 60)

    if not symbols:
        logger.warning("No symbols to test with")
        return False

    config = Config()
    daemon_manager = DaemonManager(config)
    daemon_manager.is_daemon_running()  # This updates config with correct port

    client = ThetaDataClient(config)
    data_manager = ParquetDataManager(config)

    # Test with first symbol only
    test_symbol = symbols[0]
    logger.info(f"Testing with symbol: {test_symbol}")

    try:
        # Get expirations for this symbol
        logger.info(f"Getting expirations for {test_symbol}...")
        expirations = client.get_option_expirations(test_symbol)

        if not expirations:
            logger.warning(f"  No expirations found for {test_symbol}")
            return False

        logger.info(f"  Found {len(expirations)} expirations")

        # Find an expiration that's in the future (so we can download current data for it)
        # Today is 2026-01-27, so look for expirations in 2026 or later
        test_expiration = None
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")

        for exp in expirations:
            if exp >= today:  # Find first future expiration
                test_expiration = exp
                break

        if not test_expiration:
            # Fallback to the last expiration in list (likely future)
            test_expiration = expirations[-1] if expirations else None

        if not test_expiration:
            logger.warning(f"  No suitable expiration found for {test_symbol}")
            return False

        logger.info(f"Downloading data for {test_symbol} {test_expiration}...")

        # Use a small date range for testing (last 30 days)
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

        data = client.get_option_eod(
            symbol=test_symbol,
            expiration=test_expiration,
            start_date=start_date,
            end_date=end_date
        )

        if data:
            logger.info(f"✓ Downloaded {len(data)} records")

            # Try saving to Parquet
            success = data_manager.save_option_data(
                symbol=test_symbol,
                expiration=test_expiration,
                data=data,
                mode="overwrite"
            )

            if success:
                logger.info(f"✓ Successfully saved to Parquet")

                # Try reading it back
                df = data_manager.load_option_data(test_symbol, test_expiration)
                if df is not None:
                    logger.info(f"✓ Successfully loaded from Parquet")
                    logger.info(f"  Rows: {len(df)}")
                    logger.info(f"  Columns: {list(df.columns)}")

                    if "timestamp" in df.columns:
                        logger.info(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

                    return True
                else:
                    logger.error("✗ Failed to load data back from Parquet")
                    return False
            else:
                logger.error("✗ Failed to save to Parquet")
                return False
        else:
            logger.warning(f"⚠ No data returned for {test_symbol} {test_expiration}")
            return False

    except Exception as e:
        logger.error(f"✗ Download failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_storage_stats():
    """Test querying stored option data"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Query Stored Data")
    logger.info("=" * 60)

    config = Config()
    data_manager = ParquetDataManager(config)

    stats = data_manager.get_symbol_stats("options")
    if stats:
        logger.info(f"✓ Found {len(stats)} symbols in storage")
        for symbol, stat in list(stats.items())[:3]:  # Show first 3
            logger.info(f"\n  {symbol}:")
            logger.info(f"    Rows: {stat['rows']}")
            logger.info(f"    Range: {stat['start_date']} to {stat['end_date']}")
            logger.info(f"    Size: {stat['file_size_mb']:.2f} MB")
            logger.info(f"    Expirations: {stat['expiration_count']}")
        return True
    else:
        logger.info("No data stored yet (this is expected on first run)")
        return True


def main():
    """Run all tests"""
    logger.info("\n")
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + " THETADATA OPTION DOWNLOADER - VERIFICATION TEST ".center(58) + "║")
    logger.info("╚" + "═" * 58 + "╝")

    # Test 1: Daemon connection
    if not test_daemon_connection():
        logger.error("\n✗ Cannot proceed - daemon not accessible")
        logger.error("   Please start ThetaTerminal: java -jar ThetaTerminalv3.jar")
        return False

    # Test 2: Get symbols
    symbols = test_get_symbols()

    # Test 3: Download sample data
    if symbols:
        test_download_sample_data(symbols)

    # Test 4: Query data
    test_storage_stats()

    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION COMPLETE")
    logger.info("=" * 60)
    logger.info("\nIf all tests passed:")
    logger.info("  1. Run full download:  python downloader.py")
    logger.info("  2. View results:       ~/data/thetadata/")
    logger.info("\n")

    return True


if __name__ == "__main__":
    main()
