"""
Simple sequential OI downloader for local Mac
Downloads Open Interest data for SPX options
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
import time
import json
import requests
import pyarrow as pa
import pyarrow.parquet as pq

from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def download_oi(symbols=None, year_start=None, year_end=None):
    """Download OI data sequentially"""
    config = Config()
    base_url = config.theta_base_url
    session = requests.Session()

    if symbols is None:
        symbols = ["SPXW"]

    data_dir = config.data_dir / "spx" / "oi"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Progress tracking
    progress_file = data_dir / "download_progress.json"
    if progress_file.exists():
        with open(progress_file) as f:
            progress = json.load(f)
    else:
        progress = {"completed": [], "last_update": None}

    total_records = 0
    start_time = time.time()

    for symbol in symbols:
        logger.info(f"Processing {symbol}...")

        # Get expirations
        resp = session.get(
            f"{base_url}/v3/option/list/expirations",
            params={"symbol": symbol, "format": "json"},
            timeout=60
        )
        if resp.status_code != 200:
            logger.error(f"Failed to get expirations: {resp.status_code}")
            continue

        expirations = [e["expiration"].replace("-", "") for e in resp.json().get("response", [])]

        # Filter by year
        if year_start:
            expirations = [e for e in expirations if int(e[:4]) >= year_start]
        if year_end:
            expirations = [e for e in expirations if int(e[:4]) <= year_end]

        # Only past expirations
        today = datetime.now().strftime("%Y%m%d")
        expirations = [e for e in expirations if e <= today]

        logger.info(f"  {len(expirations)} expirations to process")

        for i, exp in enumerate(expirations):
            exp_key = f"{symbol}_{exp}"
            filepath = data_dir / f"{symbol}_{exp}_oi.parquet"

            # Skip if already done
            if filepath.exists():
                logger.debug(f"  Skipping {exp} (already exists)")
                continue

            if exp_key in progress.get("completed", []):
                continue

            # Download OI for this expiration
            exp_fmt = f"{exp[:4]}-{exp[4:6]}-{exp[6:8]}"
            exp_date = datetime.strptime(exp, "%Y%m%d")
            start_date = (exp_date - timedelta(days=60)).strftime("%Y-%m-%d")
            end_date = exp_fmt

            all_data = []
            download_time = datetime.now().isoformat()

            for right in ["CALL", "PUT"]:
                time.sleep(0.25)  # Rate limit

                try:
                    resp = session.get(
                        f"{base_url}/v3/option/history/open_interest",
                        params={
                            "symbol": symbol,
                            "expiration": exp_fmt,
                            "strike": "*",
                            "right": right,
                            "start_date": start_date,
                            "end_date": end_date,
                            "format": "json"
                        },
                        timeout=120
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("response", []):
                            contract = item.get("contract", {})
                            for record in item.get("data", []):
                                all_data.append({
                                    "symbol": contract.get("symbol"),
                                    "expiration": contract.get("expiration"),
                                    "strike": contract.get("strike"),
                                    "right": contract.get("right"),
                                    "date": record.get("timestamp", "")[:10],
                                    "open_interest": record.get("open_interest"),
                                    "underlying": "SPX",
                                    "download_time": download_time,
                                })
                except Exception as e:
                    logger.error(f"  Error fetching {exp} {right}: {e}")

            # Save if we got data
            if all_data:
                table = pa.Table.from_pylist(all_data)
                pq.write_table(table, filepath, compression='snappy')
                total_records += len(all_data)

                # Update progress
                progress.setdefault("completed", []).append(exp_key)
                progress["last_update"] = datetime.now().isoformat()
                with open(progress_file, 'w') as f:
                    json.dump(progress, f)

            # Log progress
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
            logger.info(f"  [{i+1}/{len(expirations)}] {symbol} {exp}: {len(all_data):,} OI records ({rate:.1f} exp/min)")

    # Summary
    elapsed = time.time() - start_time
    logger.info(f"\nComplete: {total_records:,} total OI records in {elapsed/60:.1f} minutes")

    # Show storage
    total_size = sum(f.stat().st_size for f in data_dir.glob("*.parquet"))
    logger.info(f"Storage: {total_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["SPXW"])
    parser.add_argument("--year-start", type=int, default=2020)
    parser.add_argument("--year-end", type=int, default=None)
    args = parser.parse_args()

    download_oi(
        symbols=args.symbols,
        year_start=args.year_start,
        year_end=args.year_end
    )
