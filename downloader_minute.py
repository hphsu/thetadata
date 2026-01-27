"""
ThetaData Minute-Level Option Downloader
Uses /v3/option/history/ohlc endpoint with interval parameter
for minute-level OHLC data from local ThetaTerminal daemon
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import time
import pandas as pd
import requests

from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MinuteDataClient:
    """Client for ThetaTerminal v3 OHLC endpoint with minute-level data"""

    def __init__(self, config):
        self.config = config
        self.base_url = config.theta_base_url
        self.timeout = config.timeout
        self.session = requests.Session()
        self.last_request_time = 0
        self.request_delay = getattr(config, 'request_delay', 0.5)

    def _throttle(self):
        """Rate limit requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def get_expirations(self, symbol: str) -> Optional[List[str]]:
        """Get available expirations for a symbol"""
        try:
            self._throttle()
            response = self.session.get(
                f"{self.base_url}/v3/option/list/expirations",
                params={"symbol": symbol, "format": "json"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "response" in data:
                return [item["expiration"].replace("-", "") for item in data["response"]]
            return None

        except Exception as e:
            logger.error(f"Failed to get expirations for {symbol}: {e}")
            return None

    def get_minute_ohlc(
        self,
        symbol: str,
        expiration: str,
        date: str,
        interval: str = "1m",
        strike: str = "*",
        right: str = "both"
    ) -> Optional[List[Dict]]:
        """
        Get minute-level OHLC data for options

        Args:
            symbol: Underlying symbol (SPY, AAPL, etc.)
            expiration: Contract expiration in YYYYMMDD format
            date: Trading date in YYYYMMDD format
            interval: Bar interval (1m, 5m, 15m, 30m, 1h, etc.)
            strike: Strike price or "*" for all
            right: "call", "put", or "both"

        Returns:
            List of OHLC bar dictionaries
        """
        try:
            self._throttle()

            # Convert dates to API format if needed
            if len(expiration) == 8:
                exp_fmt = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"
            else:
                exp_fmt = expiration

            params = {
                "symbol": symbol,
                "expiration": exp_fmt,
                "strike": strike,
                "right": right,
                "interval": interval,
                "date": date,
                "format": "json"
            }

            response = self.session.get(
                f"{self.base_url}/v3/option/history/ohlc",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "response" in data:
                    # Flatten nested contract/data structure
                    flattened = []
                    for item in data["response"]:
                        if isinstance(item, dict):
                            contract = item.get("contract", {})
                            bars = item.get("data", [])

                            # Merge contract info into each bar
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
                elif isinstance(data, list):
                    return data
                return []
            elif response.status_code == 472:
                logger.warning(f"Subscription error for {symbol} {expiration}")
                return None
            else:
                logger.warning(f"HTTP {response.status_code} for {symbol} {expiration}")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout getting OHLC for {symbol} {expiration} {date}")
            return None
        except Exception as e:
            logger.error(f"Error getting OHLC for {symbol} {expiration}: {e}")
            return None


class MinuteOptionDownloader:
    """Download minute-level option data using OHLC endpoint"""

    def __init__(self, interval: str = "1m", lookback_days: int = 5):
        """
        Initialize downloader

        Args:
            interval: Bar interval (1m, 5m, 15m, 30m, 1h)
            lookback_days: Number of trading days to download
        """
        self.config = Config()
        self.client = MinuteDataClient(self.config)
        self.interval = interval
        self.lookback_days = lookback_days

        # Data storage path
        self.data_dir = self.config.data_dir / "minute" / interval
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_trading_dates(self, days: int) -> List[str]:
        """Get list of recent trading dates (excluding weekends)"""
        dates = []
        current = datetime.now()

        while len(dates) < days:
            current -= timedelta(days=1)
            # Skip weekends
            if current.weekday() < 5:  # Monday=0, Friday=4
                dates.append(current.strftime("%Y%m%d"))

        return dates

    def download_symbol(self, symbol: str) -> Dict:
        """Download minute data for a single symbol"""
        logger.info(f"Processing {symbol}...")

        results = {
            "symbol": symbol,
            "expirations": [],
            "total_rows": 0,
            "errors": []
        }

        # Get available expirations
        expirations = self.client.get_expirations(symbol)
        if not expirations:
            logger.warning(f"  No expirations found for {symbol}")
            return results

        # Filter to next 30 days only (near-term options), skip today's expiration
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y%m%d")
        cutoff = (today + timedelta(days=30)).strftime("%Y%m%d")
        near_term = [e for e in expirations if e <= cutoff and e >= tomorrow]

        if not near_term:
            logger.info(f"  No near-term expirations for {symbol}")
            return results

        logger.info(f"  Found {len(near_term)} near-term expirations")

        # Get trading dates
        trading_dates = self.get_trading_dates(self.lookback_days)
        logger.info(f"  Downloading {len(trading_dates)} trading days")

        # Download data for each expiration and date
        all_data = []

        for expiration in near_term[:3]:  # Limit to 3 expirations
            for date in trading_dates:
                try:
                    data = self.client.get_minute_ohlc(
                        symbol=symbol,
                        expiration=expiration,
                        date=date,
                        interval=self.interval
                    )

                    if data and len(data) > 0:
                        # Add metadata to each row
                        for row in data:
                            row["underlying"] = symbol
                            row["download_date"] = date
                        all_data.extend(data)
                        logger.debug(f"    {symbol} {expiration} {date}: {len(data)} rows")

                except Exception as e:
                    results["errors"].append(f"{expiration}/{date}: {str(e)}")
                    continue

        # Save to Parquet
        if all_data:
            df = pd.DataFrame(all_data)
            filepath = self.data_dir / f"{symbol}.parquet"

            # Append to existing file if it exists
            if filepath.exists():
                existing = pd.read_parquet(filepath)
                df = pd.concat([existing, df], ignore_index=True)
                df = df.drop_duplicates()

            df.to_parquet(filepath, compression='snappy', index=False)
            results["total_rows"] = len(df)
            logger.info(f"  Saved {len(df):,} rows for {symbol}")

        return results

    def run(self, symbols: List[str] = None) -> bool:
        """
        Download minute-level data for all symbols

        Args:
            symbols: List of symbols to download (default: popular ETFs/stocks)
        """
        if symbols is None:
            symbols = [
                "SPY", "QQQ", "IWM",  # Major ETFs
                "AAPL", "MSFT", "TSLA", "NVDA",  # Mega cap stocks
            ]

        logger.info("="*70)
        logger.info("THETADATA MINUTE-LEVEL OPTION DOWNLOADER")
        logger.info("="*70)
        logger.info(f"Interval: {self.interval}")
        logger.info(f"Lookback: {self.lookback_days} trading days")
        logger.info(f"Symbols: {len(symbols)}")
        logger.info(f"Output: {self.data_dir}")

        start_time = time.time()
        all_results = []
        successful = 0
        failed = 0

        # Download each symbol
        for i, symbol in enumerate(symbols, 1):
            try:
                result = self.download_symbol(symbol)
                all_results.append(result)

                if result["total_rows"] > 0:
                    successful += 1
                else:
                    failed += 1

                logger.info(f"  [{i}/{len(symbols)}] {symbol}: {result['total_rows']:,} rows")

            except Exception as e:
                failed += 1
                logger.error(f"  [{i}/{len(symbols)}] {symbol}: ERROR - {e}")

        elapsed = time.time() - start_time

        # Summary
        logger.info("\n" + "="*70)
        logger.info("DOWNLOAD SUMMARY")
        logger.info("="*70)

        total_rows = sum(r["total_rows"] for r in all_results)
        logger.info(f"Symbols processed: {len(symbols)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Total rows: {total_rows:,}")
        logger.info(f"Time elapsed: {elapsed:.1f} seconds")
        logger.info(f"\nData stored in: {self.data_dir}")

        return successful > 0


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Download minute-level option data")
    parser.add_argument("--interval", default="1m", help="Bar interval (1m, 5m, 15m, 30m, 1h)")
    parser.add_argument("--days", type=int, default=5, help="Trading days to download")
    parser.add_argument("--symbols", nargs="+", help="Symbols to download")

    args = parser.parse_args()

    downloader = MinuteOptionDownloader(
        interval=args.interval,
        lookback_days=args.days
    )

    success = downloader.run(symbols=args.symbols)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
