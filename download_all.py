"""
Download ALL available minute-level option data
Comprehensive download script for maximum data collection
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import time
import pandas as pd
import requests

from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/download_all.log')
    ]
)
logger = logging.getLogger(__name__)


class ComprehensiveDownloader:
    """Download all available option data"""

    def __init__(self):
        self.config = Config()
        self.base_url = self.config.theta_base_url
        self.session = requests.Session()
        self.timeout = 60
        self.request_delay = 0.3
        self.last_request_time = 0

        # Data directory
        self.data_dir = self.config.data_dir / "minute" / "1m"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Symbols to download
        self.symbols = [
            # Major ETFs
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLV", "XLY", "XLE", "XLU", "XLK", "XLI", "XLP", "XLB",
            # Mega cap stocks
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            # Large cap
            "BRK", "JPM", "V", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "MRK",
            "ABBV", "PEP", "KO", "COST", "AVGO", "LLY", "TMO", "MCD", "CSCO", "ACN",
            # Popular trading stocks
            "AMD", "NFLX", "CRM", "ADBE", "INTC", "PYPL", "ORCL", "BA", "DIS", "NKE",
        ]

        # Track progress
        self.total_rows = 0
        self.errors = []

    def _throttle(self):
        """Rate limit requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def get_expirations(self, symbol: str) -> Optional[List[str]]:
        """Get available expirations"""
        try:
            self._throttle()
            response = self.session.get(
                f"{self.base_url}/v3/option/list/expirations",
                params={"symbol": symbol, "format": "json"},
                timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "response" in data:
                    return [item["expiration"].replace("-", "") for item in data["response"]]
            return None
        except Exception as e:
            logger.error(f"Failed to get expirations for {symbol}: {e}")
            return None

    def get_ohlc_data(self, symbol: str, expiration: str, date: str) -> List[Dict]:
        """Get minute OHLC data for a specific symbol/expiration/date"""
        try:
            self._throttle()

            exp_fmt = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"

            response = self.session.get(
                f"{self.base_url}/v3/option/history/ohlc",
                params={
                    "symbol": symbol,
                    "expiration": exp_fmt,
                    "strike": "*",
                    "right": "both",
                    "interval": "1m",
                    "date": date,
                    "format": "json"
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "response" in data:
                    flattened = []
                    for item in data["response"]:
                        if isinstance(item, dict):
                            contract = item.get("contract", {})
                            bars = item.get("data", [])
                            for bar in bars:
                                if isinstance(bar, dict):
                                    flat_row = {
                                        "symbol": contract.get("symbol"),
                                        "expiration": contract.get("expiration"),
                                        "strike": contract.get("strike"),
                                        "right": contract.get("right"),
                                        **bar
                                    }
                                    flattened.append(flat_row)
                    return flattened
            elif response.status_code == 472:
                # Subscription limitation - skip silently
                return []
            else:
                logger.debug(f"HTTP {response.status_code} for {symbol} {expiration} {date}")
                return []

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout: {symbol} {expiration} {date}")
            return []
        except Exception as e:
            logger.debug(f"Error: {symbol} {expiration} {date}: {e}")
            return []

        return []

    def get_trading_dates(self, days: int) -> List[str]:
        """Get list of recent trading dates (excluding weekends)"""
        dates = []
        current = datetime.now()

        while len(dates) < days:
            current -= timedelta(days=1)
            if current.weekday() < 5:
                dates.append(current.strftime("%Y%m%d"))

        return dates

    def download_symbol(self, symbol: str, trading_days: int = 20) -> int:
        """Download all data for a single symbol"""
        logger.info(f"Processing {symbol}...")

        # Get expirations
        expirations = self.get_expirations(symbol)
        if not expirations:
            logger.warning(f"  No expirations for {symbol}")
            return 0

        # Filter to next 60 days (more expirations), skip today
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y%m%d")
        cutoff = (today + timedelta(days=60)).strftime("%Y%m%d")
        valid_exps = [e for e in expirations if tomorrow <= e <= cutoff]

        if not valid_exps:
            logger.info(f"  No valid expirations for {symbol}")
            return 0

        logger.info(f"  {len(valid_exps)} expirations, downloading {trading_days} days each")

        # Get trading dates
        trading_dates = self.get_trading_dates(trading_days)

        # Collect all data
        all_data = []
        requests_made = 0

        for expiration in valid_exps[:10]:  # Limit to 10 expirations per symbol
            for date in trading_dates:
                data = self.get_ohlc_data(symbol, expiration, date)
                if data:
                    all_data.extend(data)
                requests_made += 1

                # Progress indicator
                if requests_made % 20 == 0:
                    logger.info(f"    {symbol}: {requests_made} requests, {len(all_data):,} rows so far")

        # Save to parquet
        if all_data:
            df = pd.DataFrame(all_data)

            # Add metadata
            df["underlying"] = symbol
            df["download_time"] = datetime.now().isoformat()

            filepath = self.data_dir / f"{symbol}.parquet"

            # Merge with existing if present
            if filepath.exists():
                try:
                    existing = pd.read_parquet(filepath)
                    df = pd.concat([existing, df], ignore_index=True)
                    # Deduplicate
                    dedup_cols = ["symbol", "expiration", "strike", "right", "timestamp"]
                    df = df.drop_duplicates(subset=[c for c in dedup_cols if c in df.columns])
                except Exception as e:
                    logger.warning(f"  Could not merge existing data: {e}")

            df.to_parquet(filepath, compression='snappy', index=False)
            logger.info(f"  Saved {len(df):,} rows for {symbol}")
            return len(df)

        return 0

    def run(self, trading_days: int = 20):
        """Download all data for all symbols"""
        logger.info("="*70)
        logger.info("COMPREHENSIVE OPTION DATA DOWNLOAD")
        logger.info("="*70)
        logger.info(f"Symbols: {len(self.symbols)}")
        logger.info(f"Trading days: {trading_days}")
        logger.info(f"Interval: 1m (minute)")
        logger.info(f"Output: {self.data_dir}")
        logger.info("="*70)

        start_time = time.time()
        total_rows = 0
        successful = 0

        for i, symbol in enumerate(self.symbols, 1):
            try:
                rows = self.download_symbol(symbol, trading_days)
                total_rows += rows
                if rows > 0:
                    successful += 1
                logger.info(f"[{i}/{len(self.symbols)}] {symbol}: {rows:,} rows (Total: {total_rows:,})")
            except Exception as e:
                logger.error(f"[{i}/{len(self.symbols)}] {symbol}: ERROR - {e}")
                self.errors.append(f"{symbol}: {e}")

        elapsed = time.time() - start_time

        # Summary
        logger.info("\n" + "="*70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("="*70)
        logger.info(f"Symbols processed: {len(self.symbols)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Total rows: {total_rows:,}")
        logger.info(f"Time elapsed: {elapsed/60:.1f} minutes")
        logger.info(f"Data stored in: {self.data_dir}")

        if self.errors:
            logger.info(f"\nErrors ({len(self.errors)}):")
            for err in self.errors[:10]:
                logger.info(f"  - {err}")

        # Show file sizes
        logger.info("\nFile sizes:")
        total_size = 0
        for f in sorted(self.data_dir.glob("*.parquet")):
            size_mb = f.stat().st_size / (1024 * 1024)
            total_size += size_mb
            logger.info(f"  {f.name}: {size_mb:.1f} MB")
        logger.info(f"Total: {total_size:.1f} MB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download all option data")
    parser.add_argument("--days", type=int, default=20, help="Trading days to download")
    args = parser.parse_args()

    downloader = ComprehensiveDownloader()
    downloader.run(trading_days=args.days)


if __name__ == "__main__":
    main()
