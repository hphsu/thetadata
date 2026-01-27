"""
Main downloader script for ThetaData option data
Downloads historical EOD data for all available option contracts
Saves to Parquet format for efficient storage and backtesting
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict
import time

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


class OptionDownloader:
    """Download option data from ThetaTerminal"""

    def __init__(self):
        self.config = Config()
        self.client = ThetaDataClient(self.config)
        self.data_manager = ParquetDataManager(self.config)
        self.daemon_manager = DaemonManager(self.config)

    def check_daemon(self) -> bool:
        """Ensure daemon is running"""
        if self.daemon_manager.is_daemon_running():
            logger.info("✓ ThetaTerminal daemon is running")
            return True

        logger.warning("ThetaTerminal daemon is not running")
        logger.info("Attempting to auto-start daemon...")

        if self.daemon_manager.ensure_running():
            logger.info("✓ ThetaTerminal daemon started successfully")
            return True
        else:
            logger.error("✗ Failed to start ThetaTerminal daemon")
            logger.error("  Please manually start: java -jar ThetaTerminalv3.jar")
            return False

    def download_option_symbol(self, symbol: str) -> Dict:
        """
        Download all expiration data for one underlying symbol
        Returns summary of download results
        """
        try:
            logger.info(f"Processing {symbol}...")
            results = {
                "symbol": symbol,
                "expirations": [],
                "errors": []
            }

            # Get available expirations
            expirations = self.client.get_option_expirations(symbol)
            if not expirations:
                logger.warning(f"  No expirations found for {symbol}")
                return results

            logger.info(f"  Found {len(expirations)} total expirations for {symbol}")

            # Filter to recent expirations only (next 12 months) to reduce API calls
            # Most traders focus on near-term options anyway
            from datetime import datetime, timedelta
            now = datetime.now()
            cutoff_date = now + timedelta(days=365)  # Only expirations within next year
            cutoff_str = cutoff_date.strftime("%Y%m%d")

            recent_expirations = [e for e in expirations if e <= cutoff_str]
            # Limit to first 12 expirations (weekly + monthly for ~ 3 months)
            recent_expirations = recent_expirations[:12]

            logger.info(f"  Downloading {len(recent_expirations)} recent expirations for {symbol}")

            # Download data for each expiration
            for expiration in recent_expirations:
                try:
                    # Get EOD data for this expiration
                    data = self.client.get_option_eod(
                        symbol=symbol,
                        expiration=expiration
                    )

                    if data and len(data) > 0:
                        # Save to Parquet
                        success = self.data_manager.save_option_data(
                            symbol=symbol,
                            expiration=expiration,
                            data=data,
                            mode="append"
                        )
                        if success:
                            results["expirations"].append({
                                "expiration": expiration,
                                "records": len(data)
                            })
                    elif data is None:
                        # Error occurred (will be logged by client)
                        results["errors"].append(f"Failed to fetch {expiration}")
                    else:
                        # No data but not an error (past expiration, no access, etc)
                        logger.debug(f"  No data for {symbol} {expiration}")

                except Exception as e:
                    logger.warning(f"  Error downloading {symbol} {expiration}: {e}")
                    results["errors"].append(str(e))
                    continue

            return results

        except Exception as e:
            logger.error(f"Failed to process {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    def download_all_options(self, max_symbols: int = None, filter_popular: bool = True) -> bool:
        """
        Download option data for all available symbols
        max_symbols: limit to N symbols (for testing)
        filter_popular: prioritize popular/liquid symbols with VALUE access
        """
        logger.info("=" * 70)
        logger.info("THETADATA OPTION DOWNLOADER")
        logger.info("=" * 70)

        # Step 1: Check daemon
        if not self.check_daemon():
            return False

        # Step 2: Get available symbols
        logger.info("\nStep 1: Getting available option symbols...")

        # Hardcoded popular/liquid symbols known to work with VALUE subscription
        # These are prioritized, additional symbols will be fetched if available
        popular_symbols = [
            "SPY", "QQQ", "IWM", "XLF", "XLV", "XLY", "XLE", "XLU",  # Popular ETFs
            "AAPL", "MSFT", "TSLA", "NVDA", "META",  # Mega cap stocks
            "AMZN", "GOOGL", "GOOG", "BRK", "NFLX"  # Large cap
        ]

        if filter_popular:
            # Use hardcoded popular list (API symbol list is too slow to fetch)
            symbols = popular_symbols
            logger.info(f"Using {len(symbols)} popular/liquid symbols with VALUE access (skipped slow symbol list fetch)")
        else:
            # Try to fetch all symbols (may timeout)
            logger.info("Attempting to fetch all available symbols (this may take 2+ minutes)...")
            symbols = self.client.get_option_symbols()

            if not symbols:
                logger.warning("Failed to get full symbol list, falling back to popular symbols")
                symbols = popular_symbols
            else:
                logger.info(f"Found {len(symbols)} total symbols")
                # Still prioritize popular symbols
                symbols = [s for s in popular_symbols if s in symbols] + \
                          [s for s in symbols if s not in popular_symbols][:1000]  # Add up to 1000 more

        if max_symbols:
            symbols = symbols[:max_symbols]
            logger.info(f"Limiting to first {max_symbols} symbols")

        # Step 3: Download data with parallel processing
        logger.info(f"\nStep 2: Downloading option data ({len(symbols)} symbols)...")
        logger.info(f"Using {self.config.max_workers} parallel workers")

        start_time = time.time()
        all_results = []
        successful = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(self.download_option_symbol, symbol): symbol
                for symbol in symbols
            }

            # Process completed tasks
            for i, future in enumerate(as_completed(futures), 1):
                symbol = futures[future]
                try:
                    result = future.result()
                    all_results.append(result)

                    if "error" not in result:
                        successful += 1
                        exp_count = len(result.get("expirations", []))
                        logger.info(f"  [{i}/{len(symbols)}] {symbol}: {exp_count} expirations")
                    else:
                        failed += 1
                        logger.warning(f"  [{i}/{len(symbols)}] {symbol}: ERROR - {result['error']}")

                except Exception as e:
                    failed += 1
                    logger.error(f"  [{i}/{len(symbols)}] {symbol}: {e}")

        elapsed = time.time() - start_time

        # Step 4: Summary
        logger.info("\n" + "=" * 70)
        logger.info("DOWNLOAD SUMMARY")
        logger.info("=" * 70)

        total_expirations = sum(
            len(r.get("expirations", [])) for r in all_results if "error" not in r
        )
        total_records = sum(
            sum(exp.get("records", 0) for exp in r.get("expirations", []))
            for r in all_results if "error" not in r
        )

        logger.info(f"Processed:       {len(symbols)} symbols")
        logger.info(f"Successful:      {successful} symbols")
        logger.info(f"Failed:          {failed} symbols")
        logger.info(f"Total expirations: {total_expirations}")
        logger.info(f"Total records:   {total_records:,}")
        logger.info(f"Time elapsed:    {elapsed:.1f} seconds")

        # Step 5: Storage stats
        logger.info("\n" + "=" * 70)
        logger.info("STORAGE STATISTICS")
        logger.info("=" * 70)

        stats = self.data_manager.get_symbol_stats("options")
        if stats:
            logger.info(f"Stored symbols:  {len(stats)}")

            total_size = sum(s.get("file_size_mb", 0) for s in stats.values())
            total_stored = sum(s.get("rows", 0) for s in stats.values())
            logger.info(f"Total rows:      {total_stored:,}")
            logger.info(f"Total size:      {total_size:.1f} MB")

            # Show top symbols by size
            top_symbols = sorted(
                stats.items(),
                key=lambda x: x[1].get("file_size_mb", 0),
                reverse=True
            )[:5]

            if top_symbols:
                logger.info("\nTop 5 symbols by data size:")
                for symbol, stat in top_symbols:
                    logger.info(
                        f"  {symbol}: {stat['rows']:,} rows, "
                        f"{stat['file_size_mb']:.1f} MB, "
                        f"{stat['expiration_count']} expirations"
                    )

        logger.info("\n" + "=" * 70)
        logger.info("✓ Download complete!")
        logger.info("=" * 70)
        logger.info(f"\nData stored in: {self.config.data_dir}")
        logger.info("Ready for backtesting with VectorBT\n")

        return successful > 0


def main():
    """Main entry point"""
    downloader = OptionDownloader()

    # Download all available data
    success = downloader.download_all_options()

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
