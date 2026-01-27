"""
ThetaData API client for local ThetaTerminal v3 daemon communication
Uses validated v3 REST API endpoints
"""
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class ThetaDataClient:
    """HTTP client for ThetaTerminal v3 REST API"""

    def __init__(self, config):
        self.config = config
        self.base_url = config.theta_base_url
        self.timeout = config.timeout
        self.request_delay = getattr(config, 'request_delay', 0.5)  # Throttle rate limit
        self.session = requests.Session()
        self.last_request_time = 0

    def health_check(self) -> bool:
        """Check if ThetaTerminal daemon is running and v3 API is accessible"""
        try:
            # Test with option symbols list - minimal query
            response = self.session.get(
                f"{self.base_url}/v3/option/list/symbols",
                params={"format": "json"},
                timeout=self.timeout
            )
            # Any 2xx response means daemon is running
            return response.status_code < 400
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    def get_option_symbols(self) -> Optional[List[str]]:
        """
        Get list of available option symbols (underlying assets)
        Returns list of stock symbols that have options
        """
        try:
            response = self.session.get(
                f"{self.base_url}/v3/option/list/symbols",
                params={"format": "json"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "response" in data:
                # Extract symbol strings from response
                return [item["symbol"] for item in data["response"]]
            elif isinstance(data, list):
                return data
            else:
                logger.debug(f"Unexpected symbols response: {type(data)}")
                return None

        except Exception as e:
            logger.error(f"Failed to get option symbols: {e}")
            return None

    def get_option_expirations(self, symbol: str) -> Optional[List[str]]:
        """
        Get list of available expirations for a given underlying symbol
        Returns list of expiration dates in YYYYMMDD format
        """
        try:
            # Throttle requests to avoid rate limiting
            elapsed = time.time() - self.last_request_time
            if elapsed < self.request_delay:
                time.sleep(self.request_delay - elapsed)
            self.last_request_time = time.time()

            response = self.session.get(
                f"{self.base_url}/v3/option/list/expirations",
                params={"symbol": symbol, "format": "json"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "response" in data:
                # Extract expiration dates, convert YYYY-MM-DD to YYYYMMDD
                expirations = []
                for item in data["response"]:
                    exp = item.get("expiration", "")
                    # Convert "2012-06-01" to "20120601"
                    exp_clean = exp.replace("-", "")
                    expirations.append(exp_clean)
                return expirations
            else:
                logger.debug(f"Unexpected expirations response: {type(data)}")
                return None

        except Exception as e:
            logger.error(f"Failed to get expirations for {symbol}: {e}")
            return None

    def get_option_eod(
        self,
        symbol: str,
        expiration: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get end-of-day option data for a symbol and expiration
        symbol: underlying symbol (e.g., "SPY")
        expiration: contract expiration in YYYYMMDD format
        start_date/end_date: in YYYYMMDD format (required by API)
        """
        try:
            from datetime import datetime, timedelta

            # Throttle requests to avoid rate limiting
            elapsed = time.time() - self.last_request_time
            if elapsed < self.request_delay:
                time.sleep(self.request_delay - elapsed)
            self.last_request_time = time.time()

            # Convert expiration to datetime for comparison
            exp_dt = datetime.strptime(expiration, "%Y%m%d")
            today = datetime.now()

            # If expiration is in the past, skip it (no current market data available)
            if exp_dt < today:
                logger.debug(f"Expiration {expiration} is in the past, skipping")
                return []

            # Normalize dates
            if start_date:
                start_date = start_date.replace("-", "") if "-" in start_date else start_date
            if end_date:
                end_date = end_date.replace("-", "") if "-" in end_date else end_date

            # If dates not provided, use smart defaults based on expiration
            if not start_date:
                # Start from 364 days before expiration (or 364 days ago, whichever is later)
                default_start = exp_dt - timedelta(days=364)
                earliest_reasonable = today - timedelta(days=364)
                start_date = max(default_start, earliest_reasonable).strftime("%Y%m%d")

            if not end_date:
                # End date should be expiration date (or today if after expiration)
                end_date = min(exp_dt, today).strftime("%Y%m%d")

            params = {
                "symbol": symbol,
                "expiration": expiration,
                "format": "json",
                "start_date": start_date,
                "end_date": end_date
            }

            response = self.session.get(
                f"{self.base_url}/v3/option/history/eod",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Parse response - API returns nested structure by contract
            # { "response": [ { "contract": {...}, "data": [...] }, ... ] }
            if isinstance(data, dict) and "response" in data:
                # Flatten the nested response structure
                # Each item has contract details and an array of OHLC bars
                flattened = []
                for contract_item in data["response"]:
                    if isinstance(contract_item, dict):
                        contract = contract_item.get("contract", {})
                        contract_data = contract_item.get("data", [])

                        # Add contract metadata to each data point
                        for bar in contract_data:
                            bar_with_contract = {
                                "strike": contract.get("strike"),
                                "right": contract.get("right"),
                                "expiration": contract.get("expiration"),
                                "symbol": contract.get("symbol"),
                                **bar
                            }
                            flattened.append(bar_with_contract)

                return flattened if flattened else []
            elif isinstance(data, list):
                return data
            else:
                logger.debug(f"Response structure: {type(data)}")
                return [] if isinstance(data, dict) else data

        except requests.exceptions.HTTPError as e:
            if "No data found" in str(e):
                logger.debug(f"No option data for {symbol} exp={expiration}")
                return []
            logger.error(f"Failed to get option EOD for {symbol} exp={expiration}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get option EOD for {symbol} exp={expiration}: {e}")
            return None

    def get_data_with_retry(self, method: str, *args, **kwargs) -> Optional[Any]:
        """Wrapper for API calls with retry logic"""
        max_retries = self.config.max_retries if hasattr(self.config, 'max_retries') else 3
        retry_delay = self.config.retry_delay if hasattr(self.config, 'retry_delay') else 5

        for attempt in range(max_retries):
            try:
                result = getattr(self, method)(*args, **kwargs)
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"All {max_retries} attempts failed: {e}")
                    return None
