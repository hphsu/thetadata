"""
Download Open Interest (OI) data for SPX and equity options
OI is daily data - one record per contract per day
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
        logging.FileHandler('/tmp/download_oi.log')
    ]
)
logger = logging.getLogger(__name__)


class OIDownloader:
    """Download Open Interest data for options"""

    def __init__(self, root_type: str = "spx"):
        """
        Args:
            root_type: "spx" for SPX options, "equity" for stock/ETF options
        """
        self.config = Config()
        self.base_url = self.config.theta_base_url
        self.session = requests.Session()
        self.timeout = 120
        self.request_delay = 0.25
        self.last_request_time = 0
        self.max_workers = 3
        self.max_memory_percent = 80
        self.root_type = root_type

        # Thread-safe locks
        self._progress_lock = threading.Lock()
        self._throttle_lock = threading.Lock()

        # Symbols based on root type
        if root_type == "spx":
            self.symbols = ["SPXW", "SPXQ", "SPXPM"]
            self.data_dir = self.config.data_dir / "spx" / "oi"
        else:
            self.symbols = self._get_equity_symbols()
            self.data_dir = self.config.data_dir / "equity_options" / "oi"

        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Progress tracking
        self.progress_file = self.data_dir / "download_progress.json"
        self.progress = self._load_progress()

        # Stats
        self.total_rows = 0
        self.total_requests = 0
        self.start_time = None

    def _get_equity_symbols(self) -> List[str]:
        """Get list of equity symbols"""
        return [
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
            "XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE",
            "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "VXX", "SOXL", "SOXS",
            "TLT", "IEF", "HYG", "LQD", "TBT",
            "GLD", "SLV", "USO", "UNG", "GDX", "GDXJ",
            "EEM", "EFA", "FXI", "EWZ",
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "COIN", "MARA", "RIOT",
            "JPM", "BAC", "GS", "MS", "C", "WFC",
            "XOM", "CVX", "COP", "SLB",
            "UNH", "JNJ", "PFE", "MRNA", "BNTX",
            "BA", "DIS", "NKE", "SBUX", "MCD",
        ]

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
            return None
        except Exception as e:
            logger.error(f"Failed to get expirations for {symbol}: {e}")
            return None

    def get_oi_bulk(self, symbol: str, expiration: str, right: str,
                     start_date: str, end_date: str) -> List[Dict]:
        """Get OI data for ALL strikes of an expiration (bulk request)"""
        try:
            self._throttle()
            self.total_requests += 1

            exp_fmt = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

            response = self.session.get(
                f"{self.base_url}/v3/option/history/open_interest",
                params={
                    "symbol": symbol,
                    "expiration": exp_fmt,
                    "strike": "*",  # All strikes at once
                    "right": right,
                    "start_date": start_fmt,
                    "end_date": end_fmt,
                    "format": "json"
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "response" in data:
                    results = []
                    for item in data["response"]:
                        contract = item.get("contract", {})
                        oi_records = item.get("data", [])
                        for record in oi_records:
                            results.append({
                                "symbol": contract.get("symbol"),
                                "expiration": contract.get("expiration"),
                                "strike": contract.get("strike"),
                                "right": contract.get("right"),
                                "date": record.get("timestamp", "")[:10],
                                "open_interest": record.get("open_interest"),
                            })
                    return results
            return []

        except Exception as e:
            logger.debug(f"Error getting OI: {symbol} {expiration} {right}: {e}")
            return []

    def download_expiration(self, symbol: str, expiration: str) -> int:
        """Download all OI data for a single expiration (bulk request)"""
        exp_key = f"{symbol}_{expiration}"
        with self._progress_lock:
            if exp_key in self.progress.get("completed_expirations", {}):
                return self.progress["completed_expirations"][exp_key]

        self._wait_for_memory()

        # Calculate date range: from 60 days before expiration to expiration
        exp_date = datetime.strptime(expiration, "%Y%m%d")
        start_date = (exp_date - timedelta(days=60)).strftime("%Y%m%d")
        end_date = expiration

        filepath = self.data_dir / f"{symbol}_{expiration}_oi.parquet"
        all_data = []
        download_time = datetime.now().isoformat()

        # Fetch OI for all strikes at once (2 requests: CALL + PUT)
        for right in ["CALL", "PUT"]:
            data = self.get_oi_bulk(symbol, expiration, right, start_date, end_date)
            if data:
                for row in data:
                    row["underlying"] = "SPX" if self.root_type == "spx" else symbol
                    row["download_time"] = download_time
                all_data.extend(data)

        if all_data:
            table = pa.Table.from_pylist(all_data)
            pq.write_table(table, filepath, compression='snappy')

            with self._progress_lock:
                self.progress.setdefault("completed_expirations", {})[exp_key] = len(all_data)
            self._save_progress()
            return len(all_data)

        return 0

    def download_symbol(self, symbol: str, year_start: int = None, year_end: int = None) -> int:
        """Download all OI for a symbol"""
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

                            elapsed = time.time() - self.start_time
                            rate = self.total_requests / elapsed * 60 if elapsed > 0 else 0
                            mem = psutil.virtual_memory().percent
                            logger.info(f"    [{completed}/{len(past_exps)}] {symbol} {expiration}: {rows:,} OI records ({rate:.0f} req/min, mem:{mem:.0f}%)")

                        except Exception as e:
                            logger.error(f"    Error {symbol} {expiration}: {e}")

        return total_rows

    def run(self, symbols: List[str] = None, year_start: int = None, year_end: int = None):
        """Download OI data"""
        if symbols is None:
            symbols = self.symbols

        logger.info("=" * 70)
        logger.info(f"OPEN INTEREST DATA DOWNLOAD ({self.root_type.upper()})")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)} ({', '.join(symbols[:5])}...)")
        logger.info(f"Year range: {year_start or 'all'} to {year_end or 'all'}")
        logger.info(f"Output: {self.data_dir}")
        logger.info(f"Workers: {self.max_workers} (memory limit: {self.max_memory_percent}%)")
        logger.info("=" * 70)

        self.start_time = time.time()

        for symbol in symbols:
            try:
                rows = self.download_symbol(symbol, year_start, year_end)
                self.total_rows += rows
                logger.info(f"  {symbol}: {rows:,} total OI records")
            except Exception as e:
                logger.error(f"  {symbol}: ERROR - {e}")

        elapsed = time.time() - self.start_time

        logger.info("\n" + "=" * 70)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Total OI records: {self.total_rows:,}")
        logger.info(f"Total requests: {self.total_requests:,}")
        logger.info(f"Time: {elapsed/3600:.1f} hours")

        total_size = sum(f.stat().st_size for f in self.data_dir.glob("*.parquet")) / (1024 * 1024)
        file_count = len(list(self.data_dir.glob("*.parquet")))
        logger.info(f"Files: {file_count}")
        logger.info(f"Total storage: {total_size:.1f} MB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download Open Interest data")
    parser.add_argument("--type", choices=["spx", "equity"], default="spx",
                        help="Root type: spx or equity")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to download")
    parser.add_argument("--year-start", type=int, default=None, help="Start year")
    parser.add_argument("--year-end", type=int, default=None, help="End year")
    args = parser.parse_args()

    downloader = OIDownloader(root_type=args.type)
    downloader.run(
        symbols=args.symbols,
        year_start=args.year_start,
        year_end=args.year_end
    )


if __name__ == "__main__":
    main()
