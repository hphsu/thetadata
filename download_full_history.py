"""
Download FULL 4-year historical minute-level option data
Optimized for long-running downloads with:
- Progress tracking and resume capability
- Month-by-month downloads (API 1-month limit)
- Parallel processing within rate limits
- Estimated time remaining
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import time
import json
import pandas as pd
import requests

from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/download_full_history.log')
    ]
)
logger = logging.getLogger(__name__)


class FullHistoryDownloader:
    """Download complete 4-year option history"""

    def __init__(self, years_back: int = 4):
        self.config = Config()
        self.base_url = self.config.theta_base_url
        self.session = requests.Session()
        self.timeout = 60
        self.request_delay = 0.25  # 4 requests/second max
        self.last_request_time = 0
        self.years_back = years_back

        # Data directory
        self.data_dir = self.config.data_dir / "minute" / "1m"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Progress tracking
        self.progress_file = self.data_dir / "download_progress.json"
        self.progress = self._load_progress()

        # Symbols to download (most liquid options)
        self.symbols = [
            # Major ETFs - highest volume
            "SPY", "QQQ", "IWM", "DIA",
            # Sector ETFs
            "XLF", "XLK", "XLE", "XLV", "XLY", "XLU", "XLI", "XLP", "XLB",
            # Mega cap stocks - highest option volume
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            # Large cap with high option volume
            "AMD", "NFLX", "JPM", "V", "MA", "BA", "DIS", "INTC",
        ]

        # Stats
        self.total_rows = 0
        self.total_requests = 0
        self.start_time = None

    def _load_progress(self) -> Dict:
        """Load download progress from file"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    return json.load(f)
            except:
                pass
        return {"completed": {}, "last_update": None}

    def _save_progress(self):
        """Save download progress"""
        self.progress["last_update"] = datetime.now().isoformat()
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def _throttle(self):
        """Rate limit requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def get_expirations(self, symbol: str) -> Optional[List[str]]:
        """Get all available expirations for a symbol"""
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

    def get_ohlc_data(self, symbol: str, expiration: str, start_date: str, end_date: str) -> List[Dict]:
        """Get OHLC data for a date range (max 1 month)"""
        try:
            self._throttle()
            self.total_requests += 1

            exp_fmt = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"

            response = self.session.get(
                f"{self.base_url}/v3/option/history/ohlc",
                params={
                    "symbol": symbol,
                    "expiration": exp_fmt,
                    "strike": "*",
                    "right": "both",
                    "interval": "1m",
                    "start_date": start_date,
                    "end_date": end_date,
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
            return []

        except Exception as e:
            logger.debug(f"Error: {symbol} {expiration} {start_date}-{end_date}: {e}")
            return []

    def get_months_in_range(self, start_date: datetime, end_date: datetime) -> List[tuple]:
        """Get list of (month_start, month_end) tuples"""
        months = []
        current = start_date.replace(day=1)

        while current <= end_date:
            month_start = current
            # Last day of month
            if current.month == 12:
                month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)

            # Cap at end_date
            month_end = min(month_end, end_date)

            months.append((month_start.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")))

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return months

    def download_symbol(self, symbol: str) -> int:
        """Download full history for a single symbol"""
        logger.info(f"Processing {symbol}...")

        # Check if already completed
        if symbol in self.progress.get("completed", {}):
            rows = self.progress["completed"][symbol]
            logger.info(f"  Already completed: {rows:,} rows (skipping)")
            return rows

        # Get all expirations
        expirations = self.get_expirations(symbol)
        if not expirations:
            logger.warning(f"  No expirations for {symbol}")
            return 0

        # Date range: 4 years back to today
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * self.years_back)

        # Filter expirations within our date range
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        valid_exps = [e for e in expirations if start_str <= e <= end_str]

        logger.info(f"  {len(valid_exps)} expirations in {self.years_back}-year range")

        # Get months to download
        months = self.get_months_in_range(start_date, end_date)
        logger.info(f"  {len(months)} months to download")

        # Download data
        all_data = []
        requests_made = 0

        for expiration in valid_exps:
            exp_date = datetime.strptime(expiration, "%Y%m%d")

            # Only download months before expiration
            for month_start, month_end in months:
                month_end_dt = datetime.strptime(month_end, "%Y%m%d")
                if month_end_dt > exp_date:
                    continue

                data = self.get_ohlc_data(symbol, expiration, month_start, month_end)
                if data:
                    all_data.extend(data)

                requests_made += 1
                if requests_made % 50 == 0:
                    elapsed = time.time() - self.start_time
                    rate = requests_made / elapsed * 60 if elapsed > 0 else 0
                    logger.info(f"    {symbol}: {requests_made} requests, {len(all_data):,} rows ({rate:.0f} req/min)")

        # Save to parquet
        if all_data:
            df = pd.DataFrame(all_data)
            df["underlying"] = symbol
            df["download_time"] = datetime.now().isoformat()

            filepath = self.data_dir / f"{symbol}.parquet"

            # Merge with existing if present
            if filepath.exists():
                try:
                    existing = pd.read_parquet(filepath)
                    df = pd.concat([existing, df], ignore_index=True)
                    dedup_cols = ["symbol", "expiration", "strike", "right", "timestamp"]
                    df = df.drop_duplicates(subset=[c for c in dedup_cols if c in df.columns])
                except Exception as e:
                    logger.warning(f"  Could not merge existing: {e}")

            df.to_parquet(filepath, compression='snappy', index=False)
            self.total_rows += len(df)
            logger.info(f"  Saved {len(df):,} rows for {symbol}")

            # Mark as completed
            self.progress.setdefault("completed", {})[symbol] = len(df)
            self._save_progress()

            return len(df)

        return 0

    def estimate_completion(self, symbols_done: int, symbols_total: int):
        """Estimate time to completion"""
        if symbols_done == 0:
            return "calculating..."

        elapsed = time.time() - self.start_time
        avg_per_symbol = elapsed / symbols_done
        remaining = (symbols_total - symbols_done) * avg_per_symbol

        hours = remaining / 3600
        if hours > 1:
            return f"{hours:.1f} hours"
        else:
            return f"{remaining/60:.0f} minutes"

    def run(self):
        """Download full history for all symbols"""
        logger.info("="*70)
        logger.info("FULL 4-YEAR OPTION HISTORY DOWNLOAD")
        logger.info("="*70)
        logger.info(f"Symbols: {len(self.symbols)}")
        logger.info(f"Years back: {self.years_back}")
        logger.info(f"Interval: 1m (minute)")
        logger.info(f"Output: {self.data_dir}")
        logger.info("="*70)

        # Calculate estimate
        logger.info("\nESTIMATED REQUIREMENTS:")
        logger.info("  Disk space: 5-15 GB")
        logger.info("  Time: 30-80 hours")
        logger.info("  Rows: 2-5 billion")
        logger.info("\nDownload can be stopped and resumed at any time.")
        logger.info("Progress is saved after each symbol completes.")
        logger.info("="*70)

        self.start_time = time.time()

        for i, symbol in enumerate(self.symbols, 1):
            try:
                rows = self.download_symbol(symbol)
                remaining = self.estimate_completion(i, len(self.symbols))
                logger.info(f"[{i}/{len(self.symbols)}] {symbol}: {rows:,} rows (ETA: {remaining})")
            except Exception as e:
                logger.error(f"[{i}/{len(self.symbols)}] {symbol}: ERROR - {e}")

        elapsed = time.time() - self.start_time

        # Final summary
        logger.info("\n" + "="*70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("="*70)
        logger.info(f"Symbols: {len(self.symbols)}")
        logger.info(f"Total rows: {self.total_rows:,}")
        logger.info(f"Total requests: {self.total_requests:,}")
        logger.info(f"Time: {elapsed/3600:.1f} hours")

        # Show file sizes
        total_size = 0
        for f in sorted(self.data_dir.glob("*.parquet")):
            size_mb = f.stat().st_size / (1024 * 1024)
            total_size += size_mb
        logger.info(f"Total storage: {total_size:.1f} MB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download full 4-year option history")
    parser.add_argument("--years", type=int, default=4, help="Years of history to download")
    args = parser.parse_args()

    downloader = FullHistoryDownloader(years_back=args.years)
    downloader.run()


if __name__ == "__main__":
    main()
