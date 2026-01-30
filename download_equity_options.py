"""
Download equity/ETF options data for full available history
Supports major ETFs and stocks with liquid options
Timeframes: 1m, 5m, 15m, 30m, 1h
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/download_equity_options.log')
    ]
)
logger = logging.getLogger(__name__)

# Popular ETFs and stocks with liquid options
DEFAULT_SYMBOLS = [
    # Major ETFs - highest volume
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
    # Sector ETFs
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE",
    # Leveraged/Inverse ETFs
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "VXX", "SOXL", "SOXS",
    # Bond ETFs
    "TLT", "IEF", "HYG", "LQD", "TBT",
    # Commodity ETFs
    "GLD", "SLV", "USO", "UNG", "GDX", "GDXJ",
    # International ETFs
    "EEM", "EFA", "FXI", "EWZ",
    # Mega cap stocks - most liquid options
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "AMD", "NFLX", "COIN", "MARA", "RIOT",
    # Financials
    "JPM", "BAC", "GS", "MS", "C", "WFC",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Healthcare
    "UNH", "JNJ", "PFE", "MRNA", "BNTX",
    # Other popular options
    "BA", "DIS", "NKE", "SBUX", "MCD",
]


class EquityOptionsDownloader:
    """Download complete equity/ETF options history"""

    def __init__(self, interval: str = "1m"):
        self.config = Config()
        self.base_url = self.config.theta_base_url
        self.session = requests.Session()
        self.timeout = 120
        self.request_delay = 0.25
        self.last_request_time = 0
        self.interval = interval
        self.max_workers = 3
        self.max_memory_percent = 80

        # Thread-safe locks
        self._progress_lock = threading.Lock()
        self._throttle_lock = threading.Lock()

        # Data directory
        self.data_dir = self.config.data_dir / "equity_options" / interval
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Progress tracking
        self.progress_file = self.data_dir / "download_progress.json"
        self.progress = self._load_progress()

        # Stats
        self.total_rows = 0
        self.total_requests = 0
        self.start_time = None

    def _load_progress(self) -> Dict:
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    return json.load(f)
            except:
                pass
        return {"completed_expirations": {}, "last_update": None}

    def _save_progress(self):
        with self._progress_lock:
            self.progress["last_update"] = datetime.now().isoformat()
            with open(self.progress_file, 'w') as f:
                json.dump(self.progress, f, indent=2)

    def _throttle(self):
        with self._throttle_lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.request_delay:
                time.sleep(self.request_delay - elapsed)
            self.last_request_time = time.time()

    def _wait_for_memory(self):
        while psutil.virtual_memory().percent > self.max_memory_percent:
            logger.debug(f"Memory at {psutil.virtual_memory().percent}%, waiting...")
            time.sleep(1)

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
            elif response.status_code == 472:
                logger.debug(f"No expirations for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Failed to get expirations for {symbol}: {e}")
            return None

    def get_ohlc_data(self, symbol: str, expiration: str, start_date: str, end_date: str) -> List[Dict]:
        """Get OHLC data for a date range"""
        try:
            self._throttle()
            self.total_requests += 1

            exp_fmt = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

            response = self.session.get(
                f"{self.base_url}/v3/option/history/ohlc",
                params={
                    "symbol": symbol,
                    "expiration": exp_fmt,
                    "strike": "*",
                    "right": "both",
                    "interval": self.interval,
                    "start_date": start_fmt,
                    "end_date": end_fmt,
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
                logger.debug(f"No data for {symbol} {expiration}")
            return []

        except Exception as e:
            logger.debug(f"Error: {symbol} {expiration} {start_date}-{end_date}: {e}")
            return []

    def get_months_for_expiration(self, expiration: str) -> List[tuple]:
        """Get list of (month_start, month_end) tuples for an expiration"""
        exp_date = datetime.strptime(expiration, "%Y%m%d")

        # Equity options typically trade ~45 days before expiration
        # Some longer-dated options trade earlier
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
        """Download all data for a single expiration using streaming writes"""
        exp_key = f"{symbol}_{expiration}"
        with self._progress_lock:
            if exp_key in self.progress.get("completed_expirations", {}):
                return self.progress["completed_expirations"][exp_key]

        self._wait_for_memory()

        months = self.get_months_for_expiration(expiration)
        filepath = self.data_dir / f"{symbol}_{expiration}.parquet"

        total_rows = 0
        writer = None
        download_time = datetime.now().isoformat()

        try:
            for month_start, month_end in months:
                data = self.get_ohlc_data(symbol, expiration, month_start, month_end)
                if not data:
                    continue

                for row in data:
                    row["underlying"] = symbol
                    row["download_time"] = download_time

                table = pa.Table.from_pylist(data)

                if writer is None:
                    writer = pq.ParquetWriter(filepath, table.schema, compression='snappy')

                writer.write_table(table)
                total_rows += len(data)

                del data
                del table

        finally:
            if writer:
                writer.close()

        if total_rows > 0:
            with self._progress_lock:
                self.progress.setdefault("completed_expirations", {})[exp_key] = total_rows
            self._save_progress()
            return total_rows

        return 0

    def download_symbol(self, symbol: str, year_start: int = None, year_end: int = None) -> int:
        """Download all expirations for a symbol using memory-aware parallel workers"""
        logger.info(f"Processing {symbol}...")

        expirations = self.get_expirations(symbol)
        if not expirations:
            logger.warning(f"  No expirations for {symbol}")
            return 0

        if year_start:
            expirations = [e for e in expirations if int(e[:4]) >= year_start]
        if year_end:
            expirations = [e for e in expirations if int(e[:4]) <= year_end]

        today = datetime.now().strftime("%Y%m%d")
        past_exps = [e for e in expirations if e <= today]

        logger.info(f"  {len(past_exps)} historical expirations to download")
        logger.info(f"  Using {self.max_workers} workers (memory limit: {self.max_memory_percent}%)")

        total_rows = 0
        completed = 0
        pending_futures = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            exp_iter = iter(past_exps)
            finished = False

            while not finished or pending_futures:
                while not finished and len(pending_futures) < self.max_workers:
                    mem = psutil.virtual_memory().percent
                    if mem > self.max_memory_percent:
                        break

                    try:
                        exp = next(exp_iter)
                        future = executor.submit(self.download_expiration, symbol, exp)
                        pending_futures[future] = exp
                    except StopIteration:
                        finished = True
                        break

                if pending_futures:
                    done_futures = [f for f in pending_futures if f.done()]

                    if not done_futures:
                        time.sleep(0.1)
                        continue

                    for future in done_futures:
                        expiration = pending_futures.pop(future)
                        completed += 1
                        try:
                            rows = future.result()
                            total_rows += rows

                            if completed % 10 == 0 or rows > 0:
                                elapsed = time.time() - self.start_time
                                rate = self.total_requests / elapsed * 60 if elapsed > 0 else 0
                                mem = psutil.virtual_memory().percent
                                logger.info(f"    [{completed}/{len(past_exps)}] {symbol} {expiration}: {rows:,} rows ({rate:.0f} req/min, mem:{mem:.0f}%)")

                        except Exception as e:
                            logger.error(f"    Error {symbol} {expiration}: {e}")

        return total_rows

    def status(self, symbols: List[str] = None, year_start: int = None):
        """Check download status"""
        if symbols is None:
            symbols = DEFAULT_SYMBOLS

        logger.info("=" * 70)
        logger.info("EQUITY OPTIONS DOWNLOAD STATUS")
        logger.info("=" * 70)

        today = datetime.now().strftime("%Y%m%d")
        total_available = 0
        total_downloaded = 0
        symbols_with_data = []

        for symbol in symbols:
            exps = self.get_expirations(symbol)
            if not exps:
                continue

            available = set(e for e in exps if e <= today)
            if year_start:
                available = set(e for e in available if int(e[:4]) >= year_start)

            downloaded = set(f.stem.split('_')[1] for f in self.data_dir.glob(f"{symbol}_*.parquet"))
            missing = len(available) - len(downloaded)

            if len(available) > 0:
                symbols_with_data.append((symbol, len(available), len(downloaded), missing))
                total_available += len(available)
                total_downloaded += len(downloaded)

        # Sort by missing count (descending)
        symbols_with_data.sort(key=lambda x: x[2], reverse=True)

        for symbol, avail, downloaded, missing in symbols_with_data[:20]:
            pct = (downloaded / avail * 100) if avail > 0 else 0
            logger.info(f"  {symbol:6s}: {downloaded:4d}/{avail:4d} ({pct:5.1f}%) - {missing:4d} missing")

        if len(symbols_with_data) > 20:
            logger.info(f"  ... and {len(symbols_with_data) - 20} more symbols")

        logger.info("\n" + "=" * 70)
        logger.info(f"Total symbols: {len(symbols_with_data)}")
        logger.info(f"Total available: {total_available:,}")
        logger.info(f"Total downloaded: {total_downloaded:,}")
        logger.info(f"Total missing: {total_available - total_downloaded:,}")

        if total_available > 0:
            pct = (total_downloaded / total_available) * 100
            logger.info(f"Progress: {pct:.1f}%")

        # Storage info
        total_size = sum(f.stat().st_size for f in self.data_dir.glob("*.parquet")) / (1024 * 1024)
        file_count = len(list(self.data_dir.glob("*.parquet")))
        logger.info(f"Files on disk: {file_count}")
        logger.info(f"Storage used: {total_size:.1f} MB")

        return total_available - total_downloaded

    def run(self, symbols: List[str] = None, year_start: int = None, year_end: int = None):
        """Download equity options data"""
        if symbols is None:
            symbols = DEFAULT_SYMBOLS

        logger.info("=" * 70)
        logger.info("EQUITY OPTIONS DATA DOWNLOAD")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)} ({', '.join(symbols[:5])}...)")
        logger.info(f"Interval: {self.interval}")
        logger.info(f"Year range: {year_start or 'all'} to {year_end or 'all'}")
        logger.info(f"Output: {self.data_dir}")
        logger.info(f"Workers: {self.max_workers} (memory limit: {self.max_memory_percent}%)")
        logger.info("=" * 70)

        self.start_time = time.time()

        for symbol in symbols:
            try:
                rows = self.download_symbol(symbol, year_start, year_end)
                self.total_rows += rows
                logger.info(f"  {symbol}: {rows:,} total rows")
            except Exception as e:
                logger.error(f"  {symbol}: ERROR - {e}")

        elapsed = time.time() - self.start_time

        logger.info("\n" + "=" * 70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Total rows: {self.total_rows:,}")
        logger.info(f"Total requests: {self.total_requests:,}")
        logger.info(f"Time: {elapsed/3600:.1f} hours")

        total_size = sum(f.stat().st_size for f in self.data_dir.glob("*.parquet")) / (1024 * 1024)
        file_count = len(list(self.data_dir.glob("*.parquet")))
        logger.info(f"Files: {file_count}")
        logger.info(f"Total storage: {total_size:.1f} MB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download equity/ETF options data")
    parser.add_argument("--interval", default="1m", help="Bar interval (1m, 5m, 15m, 30m, 1h)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to download")
    parser.add_argument("--year-start", type=int, default=None, help="Start year")
    parser.add_argument("--year-end", type=int, default=None, help="End year")
    parser.add_argument("--status", action="store_true", help="Show download status")
    args = parser.parse_args()

    downloader = EquityOptionsDownloader(interval=args.interval)

    if args.status:
        downloader.status(symbols=args.symbols, year_start=args.year_start)
    else:
        downloader.run(
            symbols=args.symbols,
            year_start=args.year_start,
            year_end=args.year_end
        )


if __name__ == "__main__":
    main()
