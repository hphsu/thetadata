"""
Download ALL SPX options data for full available history
Covers SPXW (weekly), SPXQ (quarterly), SPXPM (PM-settled)
Supports all timeframes: 1m, 5m, 15m, 30m, 1h
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
        logging.FileHandler('/tmp/download_spx.log')
    ]
)
logger = logging.getLogger(__name__)


class SPXDownloader:
    """Download complete SPX options history"""

    def __init__(self, interval: str = "1m"):
        self.config = Config()
        self.base_url = self.config.theta_base_url
        self.session = requests.Session()
        self.timeout = 120
        self.request_delay = 0.25  # 4 requests/second max
        self.last_request_time = 0
        self.interval = interval

        # SPX symbols (weekly is the main one)
        self.symbols = ["SPXW", "SPXQ", "SPXPM"]

        # Data directory
        self.data_dir = self.config.data_dir / "spx" / interval
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Progress tracking
        self.progress_file = self.data_dir / "download_progress.json"
        self.progress = self._load_progress()

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
        return {"completed_expirations": {}, "last_update": None}

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
                    "interval": self.interval,
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

    def get_months_for_expiration(self, expiration: str) -> List[tuple]:
        """Get list of (month_start, month_end) tuples for an expiration"""
        exp_date = datetime.strptime(expiration, "%Y%m%d")

        # Start from 60 days before expiration (typical active trading period)
        # or from data start date (2012-06-01), whichever is later
        data_start = datetime(2012, 6, 1)
        start_date = max(exp_date - timedelta(days=60), data_start)
        end_date = exp_date

        months = []
        current = start_date.replace(day=1)

        while current <= end_date:
            month_start = current
            if current.month == 12:
                month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)

            month_end = min(month_end, end_date)
            months.append((month_start.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")))

            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return months

    def download_expiration(self, symbol: str, expiration: str) -> int:
        """Download all data for a single expiration"""
        # Check if already completed
        exp_key = f"{symbol}_{expiration}"
        if exp_key in self.progress.get("completed_expirations", {}):
            return self.progress["completed_expirations"][exp_key]

        # Get months to download
        months = self.get_months_for_expiration(expiration)

        all_data = []
        for month_start, month_end in months:
            data = self.get_ohlc_data(symbol, expiration, month_start, month_end)
            if data:
                all_data.extend(data)

        if all_data:
            # Save to parquet (one file per expiration)
            df = pd.DataFrame(all_data)
            df["underlying"] = "SPX"
            df["download_time"] = datetime.now().isoformat()

            filepath = self.data_dir / f"{symbol}_{expiration}.parquet"
            df.to_parquet(filepath, compression='snappy', index=False)

            # Mark as completed
            self.progress.setdefault("completed_expirations", {})[exp_key] = len(df)
            self._save_progress()

            return len(df)

        return 0

    def download_symbol(self, symbol: str, year_start: int = None, year_end: int = None) -> int:
        """Download all expirations for a symbol"""
        logger.info(f"Processing {symbol}...")

        expirations = self.get_expirations(symbol)
        if not expirations:
            logger.warning(f"  No expirations for {symbol}")
            return 0

        # Filter by year range if specified
        if year_start:
            expirations = [e for e in expirations if int(e[:4]) >= year_start]
        if year_end:
            expirations = [e for e in expirations if int(e[:4]) <= year_end]

        # Filter to past expirations only (skip future ones)
        today = datetime.now().strftime("%Y%m%d")
        past_exps = [e for e in expirations if e <= today]

        logger.info(f"  {len(past_exps)} historical expirations to download")

        total_rows = 0
        for i, expiration in enumerate(past_exps, 1):
            try:
                rows = self.download_expiration(symbol, expiration)
                total_rows += rows

                if i % 10 == 0 or rows > 0:
                    elapsed = time.time() - self.start_time
                    rate = self.total_requests / elapsed * 60 if elapsed > 0 else 0
                    logger.info(f"    [{i}/{len(past_exps)}] {symbol} {expiration}: {rows:,} rows ({rate:.0f} req/min)")

            except Exception as e:
                logger.error(f"    Error {symbol} {expiration}: {e}")

        return total_rows

    def estimate_download(self):
        """Estimate download time and size"""
        total_exps = 0
        for symbol in self.symbols:
            exps = self.get_expirations(symbol)
            if exps:
                today = datetime.now().strftime("%Y%m%d")
                past_exps = [e for e in exps if e <= today]
                total_exps += len(past_exps)
                logger.info(f"  {symbol}: {len(past_exps)} historical expirations")

        # Each expiration = ~2-3 months of data = 2-3 API requests
        # Each request = ~0.3 seconds
        # Total time = total_exps * 2.5 * 0.3 = ~0.75 seconds per expiration
        est_hours = (total_exps * 0.75) / 3600

        # Estimate size: ~500KB per expiration average
        est_gb = (total_exps * 0.5) / 1000

        logger.info(f"\nESTIMATES:")
        logger.info(f"  Total expirations: {total_exps}")
        logger.info(f"  Estimated time: {est_hours:.1f} hours")
        logger.info(f"  Estimated size: {est_gb:.1f} GB")

        return total_exps

    def status(self, year_start: int = None):
        """Check download status - compare available vs downloaded"""
        logger.info("=" * 70)
        logger.info("SPX DOWNLOAD STATUS")
        logger.info("=" * 70)

        today = datetime.now().strftime("%Y%m%d")
        total_available = 0
        total_downloaded = 0
        total_missing = 0
        all_missing = []

        for symbol in self.symbols:
            # Get available from API
            exps = self.get_expirations(symbol)
            if not exps:
                continue

            available = set(e for e in exps if e <= today)
            if year_start:
                available = set(e for e in available if int(e[:4]) >= year_start)

            # Get downloaded files
            downloaded = set(f.stem.split('_')[1] for f in self.data_dir.glob(f"{symbol}_*.parquet"))

            missing = sorted(available - downloaded)

            logger.info(f"\n{symbol}:")
            logger.info(f"  Available: {len(available)}")
            logger.info(f"  Downloaded: {len(downloaded)}")
            logger.info(f"  Missing: {len(missing)}")

            if missing:
                all_missing.extend([(symbol, e) for e in missing])

            total_available += len(available)
            total_downloaded += len(downloaded)
            total_missing += len(missing)

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total available: {total_available}")
        logger.info(f"Total downloaded: {total_downloaded}")
        logger.info(f"Total missing: {total_missing}")

        if total_available > 0:
            pct = (total_downloaded / total_available) * 100
            logger.info(f"Progress: {pct:.1f}%")

        # Storage info
        total_size = 0
        file_count = 0
        for f in self.data_dir.glob("*.parquet"):
            total_size += f.stat().st_size / (1024 * 1024)
            file_count += 1
        logger.info(f"Files on disk: {file_count}")
        logger.info(f"Storage used: {total_size:.1f} MB")

        # Show first few missing
        if all_missing:
            logger.info(f"\nFirst 10 missing expirations:")
            for symbol, exp in all_missing[:10]:
                logger.info(f"  {symbol} {exp}")
            if len(all_missing) > 10:
                logger.info(f"  ... and {len(all_missing) - 10} more")

        return total_missing

    def run(self, symbols: List[str] = None, year_start: int = None, year_end: int = None):
        """Download all SPX data"""
        if symbols is None:
            symbols = self.symbols

        logger.info("="*70)
        logger.info("SPX OPTIONS DATA DOWNLOAD")
        logger.info("="*70)
        logger.info(f"Symbols: {symbols}")
        logger.info(f"Interval: {self.interval}")
        logger.info(f"Year range: {year_start or 'all'} to {year_end or 'all'}")
        logger.info(f"Output: {self.data_dir}")
        logger.info("="*70)

        # Show estimates
        self.estimate_download()

        logger.info("\nDownload can be stopped and resumed at any time.")
        logger.info("Progress is saved after each expiration completes.")
        logger.info("="*70)

        self.start_time = time.time()

        for symbol in symbols:
            try:
                rows = self.download_symbol(symbol, year_start, year_end)
                self.total_rows += rows
                logger.info(f"  {symbol}: {rows:,} total rows")
            except Exception as e:
                logger.error(f"  {symbol}: ERROR - {e}")

        elapsed = time.time() - self.start_time

        # Final summary
        logger.info("\n" + "="*70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("="*70)
        logger.info(f"Symbols: {symbols}")
        logger.info(f"Total rows: {self.total_rows:,}")
        logger.info(f"Total requests: {self.total_requests:,}")
        logger.info(f"Time: {elapsed/3600:.1f} hours")

        # Show file sizes
        total_size = 0
        file_count = 0
        for f in self.data_dir.glob("*.parquet"):
            size_mb = f.stat().st_size / (1024 * 1024)
            total_size += size_mb
            file_count += 1
        logger.info(f"Files: {file_count}")
        logger.info(f"Total storage: {total_size:.1f} MB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download SPX options data")
    parser.add_argument("--interval", default="1m", help="Bar interval (1m, 5m, 15m, 30m, 1h)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to download (SPXW, SPXQ, SPXPM)")
    parser.add_argument("--year-start", type=int, default=None, help="Start year (default: all)")
    parser.add_argument("--year-end", type=int, default=None, help="End year (default: all)")
    parser.add_argument("--estimate-only", action="store_true", help="Only show estimates, don't download")
    parser.add_argument("--status", action="store_true", help="Show download status (available vs downloaded)")
    args = parser.parse_args()

    downloader = SPXDownloader(interval=args.interval)

    if args.status:
        downloader.status(year_start=args.year_start)
    elif args.estimate_only:
        downloader.estimate_download()
    else:
        downloader.run(
            symbols=args.symbols,
            year_start=args.year_start,
            year_end=args.year_end
        )


if __name__ == "__main__":
    main()
