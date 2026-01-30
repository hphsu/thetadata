"""
Download stock/ETF OHLC data from ThetaData
Supports all timeframes: 1m, 5m, 15m, 30m, 1h, daily
VALUE tier: 2021-01-01+ with 15-min delay
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        logging.FileHandler('/tmp/download_stocks.log')
    ]
)
logger = logging.getLogger(__name__)

# Popular stocks and ETFs to download
DEFAULT_SYMBOLS = [
    # Major ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
    # Sector ETFs
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE",
    # Leveraged ETFs
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "VXX",
    # Bond ETFs
    "TLT", "IEF", "HYG", "LQD",
    # Commodity ETFs
    "GLD", "SLV", "USO", "UNG",
    # International ETFs
    "EEM", "EFA", "FXI",
    # Mega cap stocks
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "BRK.B", "JPM", "V", "MA", "UNH", "JNJ", "WMT", "PG",
    # Popular trading stocks
    "AMD", "INTC", "NFLX", "DIS", "BA", "GS", "MS",
    "C", "BAC", "WFC", "XOM", "CVX", "COP",
]


class StockDownloader:
    """Download stock/ETF OHLC data"""

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
        self.data_dir = self.config.data_dir / "stocks" / interval
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Progress tracking
        self.progress_file = self.data_dir / "download_progress.json"
        self.progress = self._load_progress()

        # Stats
        self.total_rows = 0
        self.total_requests = 0
        self.start_time = None

        # VALUE tier starts from 2021-01-01
        self.data_start_date = datetime(2021, 1, 1)

    def _load_progress(self) -> Dict:
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    return json.load(f)
            except:
                pass
        return {"completed_months": {}, "last_update": None}

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

    def get_ohlc_data(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """Get OHLC data for a date range"""
        try:
            self._throttle()
            self.total_requests += 1

            # Format dates as YYYY-MM-DD
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

            response = self.session.get(
                f"{self.base_url}/v3/stock/history/ohlc",
                params={
                    "symbol": symbol,
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
                    rows = []
                    for item in data["response"]:
                        if isinstance(item, dict):
                            item["symbol"] = symbol
                            rows.append(item)
                    return rows
            elif response.status_code == 472:
                logger.debug(f"No data for {symbol} {start_date}-{end_date}")
            else:
                logger.debug(f"HTTP {response.status_code} for {symbol}")
            return []

        except Exception as e:
            logger.debug(f"Error: {symbol} {start_date}-{end_date}: {e}")
            return []

    def get_months_to_download(self, symbol: str) -> List[tuple]:
        """Get list of (year, month) tuples to download"""
        months = []
        current = self.data_start_date.replace(day=1)
        today = datetime.now()

        while current <= today:
            month_start = current
            if current.month == 12:
                month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)

            month_end = min(month_end, today)
            months.append((
                month_start.strftime("%Y%m%d"),
                month_end.strftime("%Y%m%d"),
                f"{current.year}{current.month:02d}"
            ))

            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return months

    def download_symbol(self, symbol: str) -> int:
        """Download all data for a single symbol using streaming writes"""
        self._wait_for_memory()

        months = self.get_months_to_download(symbol)
        filepath = self.data_dir / f"{symbol}.parquet"

        # Check which months are already completed
        completed_key = f"{symbol}_months"
        with self._progress_lock:
            completed_months = set(self.progress.get("completed_months", {}).get(completed_key, []))

        months_to_download = [(s, e, m) for s, e, m in months if m not in completed_months]

        if not months_to_download:
            # All months done, return cached count
            with self._progress_lock:
                return self.progress.get("completed_months", {}).get(f"{symbol}_rows", 0)

        total_rows = 0
        writer = None
        download_time = datetime.now().isoformat()
        newly_completed = []

        try:
            for start_date, end_date, month_key in months_to_download:
                data = self.get_ohlc_data(symbol, start_date, end_date)
                if not data:
                    newly_completed.append(month_key)
                    continue

                # Add metadata
                for row in data:
                    row["download_time"] = download_time

                # Convert to PyArrow and write
                table = pa.Table.from_pylist(data)

                if writer is None:
                    # If file exists, we need to read schema and append
                    if filepath.exists():
                        existing = pq.read_table(filepath)
                        writer = pq.ParquetWriter(filepath, existing.schema, compression='snappy')
                        writer.write_table(existing)
                        del existing
                    else:
                        writer = pq.ParquetWriter(filepath, table.schema, compression='snappy')

                writer.write_table(table)
                total_rows += len(data)
                newly_completed.append(month_key)

                del data
                del table

        finally:
            if writer:
                writer.close()

        # Update progress
        with self._progress_lock:
            if completed_key not in self.progress.get("completed_months", {}):
                self.progress.setdefault("completed_months", {})[completed_key] = []
            self.progress["completed_months"][completed_key].extend(newly_completed)
            self.progress["completed_months"][f"{symbol}_rows"] = total_rows
        self._save_progress()

        return total_rows

    def download_all(self, symbols: List[str] = None) -> int:
        """Download all symbols using memory-aware parallel workers"""
        if symbols is None:
            symbols = DEFAULT_SYMBOLS

        logger.info("=" * 70)
        logger.info("STOCK/ETF DATA DOWNLOAD")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Interval: {self.interval}")
        logger.info(f"Date range: {self.data_start_date.date()} to today")
        logger.info(f"Output: {self.data_dir}")
        logger.info(f"Workers: {self.max_workers} (memory limit: {self.max_memory_percent}%)")
        logger.info("=" * 70)

        self.start_time = time.time()
        total_rows = 0
        completed = 0
        pending_futures = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            symbol_iter = iter(symbols)
            finished = False

            while not finished or pending_futures:
                # Submit new tasks if under memory limit
                while not finished and len(pending_futures) < self.max_workers:
                    mem = psutil.virtual_memory().percent
                    if mem > self.max_memory_percent:
                        break

                    try:
                        symbol = next(symbol_iter)
                        future = executor.submit(self.download_symbol, symbol)
                        pending_futures[future] = symbol
                    except StopIteration:
                        finished = True
                        break

                # Process completed tasks
                if pending_futures:
                    done_futures = [f for f in pending_futures if f.done()]

                    if not done_futures:
                        time.sleep(0.1)
                        continue

                    for future in done_futures:
                        symbol = pending_futures.pop(future)
                        completed += 1
                        try:
                            rows = future.result()
                            total_rows += rows

                            elapsed = time.time() - self.start_time
                            rate = self.total_requests / elapsed * 60 if elapsed > 0 else 0
                            mem = psutil.virtual_memory().percent
                            logger.info(f"  [{completed}/{len(symbols)}] {symbol}: {rows:,} rows ({rate:.0f} req/min, mem:{mem:.0f}%)")

                        except Exception as e:
                            logger.error(f"  Error {symbol}: {e}")

        elapsed = time.time() - self.start_time

        logger.info("\n" + "=" * 70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Total rows: {total_rows:,}")
        logger.info(f"Total requests: {self.total_requests:,}")
        logger.info(f"Time: {elapsed/60:.1f} minutes")

        # Show file sizes
        total_size = sum(f.stat().st_size for f in self.data_dir.glob("*.parquet")) / (1024 * 1024)
        file_count = len(list(self.data_dir.glob("*.parquet")))
        logger.info(f"Files: {file_count}")
        logger.info(f"Total storage: {total_size:.1f} MB")

        return total_rows

    def status(self):
        """Show download status"""
        logger.info("=" * 70)
        logger.info("STOCK/ETF DOWNLOAD STATUS")
        logger.info("=" * 70)

        files = list(self.data_dir.glob("*.parquet"))
        symbols_done = [f.stem for f in files]

        logger.info(f"Downloaded: {len(symbols_done)} symbols")
        logger.info(f"Default list: {len(DEFAULT_SYMBOLS)} symbols")

        missing = [s for s in DEFAULT_SYMBOLS if s not in symbols_done]
        if missing:
            logger.info(f"Missing: {missing[:10]}{'...' if len(missing) > 10 else ''}")

        total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)
        logger.info(f"Storage: {total_size:.1f} MB")

        return len(missing)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download stock/ETF OHLC data")
    parser.add_argument("--interval", default="1m", help="Bar interval (1m, 5m, 15m, 30m, 1h, daily)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to download (default: major ETFs and stocks)")
    parser.add_argument("--status", action="store_true", help="Show download status")
    args = parser.parse_args()

    downloader = StockDownloader(interval=args.interval)

    if args.status:
        downloader.status()
    else:
        downloader.download_all(symbols=args.symbols)


if __name__ == "__main__":
    main()
