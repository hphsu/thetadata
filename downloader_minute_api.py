"""
ThetaData Direct API Downloader - Minute-level Option Data
Uses direct HTTP API (api.thetadata.us) instead of local daemon
Enables access to minute-level and real-time data
"""
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import time
import pandas as pd

from config_direct_api import DirectAPIConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DirectAPIClient:
    """Direct ThetaData HTTP API client for minute-level option data"""

    def __init__(self, config):
        self.config = config
        self.base_url = config.api_base_url
        self.api_key = config.api_key
        self.timeout = config.timeout
        self.session = requests.Session()
        self.last_request_time = 0

    def _validate_api_key(self) -> bool:
        """Validate API key before attempting downloads"""
        if not self.api_key:
            logger.error("❌ API key not found in THETADATA_API_KEY environment variable")
            logger.error("   Set it with: export THETADATA_API_KEY='your_key'")
            logger.error("   Get key from: https://app.thetadata.us/account/api")
            return False
        return True

    def _throttle_request(self):
        """Throttle requests to respect API rate limits"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)
        self.last_request_time = time.time()

    def get_minute_data(
        self,
        symbol: str,
        expiration: str,
        strike: float,
        right: str,
        start_date: str,
        end_date: str
    ) -> Optional[List[Dict]]:
        """
        Get minute-level option data
        symbol: underlying (SPY, AAPL, etc)
        expiration: YYYYMMDD format
        strike: strike price (400.0, 405.5, etc)
        right: 'C' for call, 'P' for put
        """
        try:
            self._throttle_request()

            # Convert YYYYMMDD to YYYY-MM-DD format
            if len(start_date) == 8:
                start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            if len(end_date) == 8:
                end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

            # Also convert expiration
            if len(expiration) == 8:
                exp_date = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"
            else:
                exp_date = expiration

            url = f"{self.base_url}/option/history/minute"
            params = {
                "root": symbol,
                "expiration": exp_date,
                "strike": strike,
                "right": right,
                "start_date": start_date,
                "end_date": end_date,
                "format": "json"
            }

            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return data
                elif isinstance(data, dict) and "data" in data:
                    return data["data"]
                else:
                    return None
            elif response.status_code == 401:
                logger.error(f"Unauthorized: Invalid API key for {symbol}")
                return None
            elif response.status_code == 404:
                # No data available for this contract
                return []
            else:
                logger.warning(f"HTTP {response.status_code} for {symbol} {exp_date} {strike}{right}")
                return None

        except Exception as e:
            logger.warning(f"Error fetching minute data for {symbol} {expiration}: {e}")
            return None

    def get_option_expirations(self, symbol: str) -> Optional[List[str]]:
        """Get available expirations for a symbol"""
        try:
            self._throttle_request()

            url = f"{self.base_url}/option/expirations"
            params = {"root": symbol, "format": "json"}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                # Convert from YYYY-MM-DD to YYYYMMDD format
                if isinstance(data, list):
                    return [d.replace("-", "") for d in data]
                return None
            else:
                logger.warning(f"Failed to get expirations for {symbol}: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.warning(f"Error getting expirations for {symbol}: {e}")
            return None

    def get_option_chains(self, symbol: str, expiration: str) -> Optional[List[Dict]]:
        """Get option chains (strikes and rights available)"""
        try:
            self._throttle_request()

            # Convert YYYYMMDD to YYYY-MM-DD if needed
            if len(expiration) == 8:
                exp_date = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"
            else:
                exp_date = expiration

            url = f"{self.base_url}/option/chains"
            params = {"root": symbol, "expiration": exp_date, "format": "json"}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"Failed to get chains for {symbol}: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.debug(f"Error getting chains for {symbol}: {e}")
            return None


class MinuteOptionDownloader:
    """Download minute-level option data using ThetaData direct API"""

    def __init__(self):
        self.config = DirectAPIConfig()
        self.client = DirectAPIClient(self.config)

    def download_symbol_minute_data(self, symbol: str, days_back: int = 30) -> Dict:
        """Download minute-level data for a symbol"""
        try:
            logger.info(f"Processing {symbol} (minute-level)...")

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

            logger.info(f"  Found {len(expirations)} expirations for {symbol}")

            # Filter to next 12 months only
            now = datetime.now()
            cutoff_date = now + timedelta(days=365)
            cutoff_str = cutoff_date.strftime("%Y%m%d")

            recent_expirations = [e for e in expirations if e <= cutoff_str][:12]
            logger.info(f"  Downloading {len(recent_expirations)} recent expirations")

            # For each expiration, get chains and download minute data
            end_date = now.strftime("%Y%m%d")
            start_date = (now - timedelta(days=days_back)).strftime("%Y%m%d")

            for expiration in recent_expirations:
                try:
                    # Get option chains for this expiration
                    chains = self.client.get_option_chains(symbol, expiration)
                    if not chains:
                        logger.debug(f"    No chains for {symbol} {expiration}")
                        continue

                    # Convert chains to list of (strike, right) tuples
                    contracts = []
                    if isinstance(chains, list):
                        for chain in chains:
                            strike = chain.get("strike")
                            right = chain.get("right")
                            if strike and right:
                                contracts.append((strike, right))
                    elif isinstance(chains, dict):
                        # Handle nested structure
                        for strike, rights in chains.items():
                            if isinstance(rights, list):
                                for right in rights:
                                    contracts.append((float(strike), right))

                    logger.info(f"    Found {len(contracts)} contracts for {symbol} {expiration}")

                    # Download minute data for first few contracts (testing)
                    downloaded = 0
                    for strike, right in contracts[:5]:  # Limit to first 5 for testing
                        data = self.client.get_minute_data(
                            symbol=symbol,
                            expiration=expiration,
                            strike=strike,
                            right=right,
                            start_date=start_date,
                            end_date=end_date
                        )

                        if data and len(data) > 0:
                            # Save to Parquet
                            self._save_minute_data(
                                symbol=symbol,
                                expiration=expiration,
                                strike=strike,
                                right=right,
                                data=data
                            )
                            downloaded += 1

                    if downloaded > 0:
                        results["expirations"].append({
                            "expiration": expiration,
                            "contracts": len(contracts),
                            "downloaded": downloaded
                        })
                        logger.info(f"    Downloaded {downloaded} contracts for {symbol} {expiration}")

                except Exception as e:
                    logger.warning(f"    Error processing {symbol} {expiration}: {e}")
                    results["errors"].append(str(e))
                    continue

            return results

        except Exception as e:
            logger.error(f"Failed to process {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    def _save_minute_data(
        self,
        symbol: str,
        expiration: str,
        strike: float,
        right: str,
        data: List[Dict]
    ) -> bool:
        """Save minute data to Parquet"""
        try:
            df = pd.DataFrame(data)

            # Get save path
            save_dir = self.config.get_data_path(symbol)
            filename = f"{symbol}_{expiration}_{strike}_{right}.parquet"
            filepath = save_dir / filename

            df.to_parquet(filepath, compression='snappy', index=False)
            logger.debug(f"    Saved {len(df)} rows to {filename}")
            return True

        except Exception as e:
            logger.warning(f"Failed to save data: {e}")
            return False

    def run(self) -> bool:
        """Download minute-level data for all symbols"""
        logger.info("="*70)
        logger.info("THETADATA DIRECT API - MINUTE-LEVEL OPTION DATA")
        logger.info("="*70)

        # Validate API key
        if not self.client._validate_api_key():
            return False

        logger.info(f"\nAPI Key: ✅ Found")
        logger.info(f"Data type: {self.config.data_type}")
        logger.info(f"Lookback: {self.config.lookback_days} days")
        logger.info(f"Symbols: {len(self.config.option_symbols)}")

        # Download data for each symbol
        all_results = []
        successful = 0
        failed = 0

        start_time = time.time()

        logger.info(f"\nDownloading minute-level data...\n")

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(
                    self.download_symbol_minute_data,
                    symbol,
                    self.config.lookback_days
                ): symbol
                for symbol in self.config.option_symbols
            }

            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result = future.result()
                    all_results.append(result)
                    if "error" not in result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"Error downloading {symbol}: {e}")

        elapsed = time.time() - start_time

        # Summary
        logger.info("\n" + "="*70)
        logger.info("DOWNLOAD SUMMARY")
        logger.info("="*70)
        logger.info(f"Symbols processed: {len(self.config.option_symbols)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Time elapsed: {elapsed:.1f} seconds")
        logger.info(f"\nData stored in: {self.config.data_dir / 'direct_api' / 'minute'}")

        return successful > 0


def main():
    """Main entry point"""
    downloader = MinuteOptionDownloader()
    success = downloader.run()
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
