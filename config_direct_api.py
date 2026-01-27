"""
Configuration for ThetaData Direct HTTP API (minute-level data)
vs Local Daemon API (EOD data only)
"""
import os
from pathlib import Path
from datetime import datetime
import json

class DirectAPIConfig:
    """Configuration for ThetaData direct HTTP API with minute-level data"""

    def __init__(self):
        # API Configuration
        self.api_base_url = "https://api.thetadata.us"
        self.api_key = os.environ.get('THETADATA_API_KEY')

        if not self.api_key:
            print("\n⚠️  WARNING: THETADATA_API_KEY not found in environment")
            print("   To use minute-level data, set: export THETADATA_API_KEY='your_key'")
            print("   Get your key from: https://app.thetadata.us/account/api")
            print()

        # Data storage
        self.data_dir = Path.home() / "data" / "thetadata"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Metadata file for tracking downloads
        self.metadata_file = self.data_dir / "metadata_direct_api.json"

        # API Configuration for minute-level data
        self.timeout = 30
        self.max_retries = 3
        self.retry_delay = 5  # seconds

        # Download configuration
        self.max_workers = 2  # Direct API can handle more concurrency
        self.batch_size = 10  # Symbols per batch
        self.request_delay = 0.5  # Seconds between requests

        # Data granularity
        self.data_type = "minute"  # minute, daily, or tick
        self.lookback_days = 30  # How many days of minute data to download

        # Option symbols to download
        self.option_symbols = [
            "SPY", "QQQ", "IWM", "XLF", "XLV", "XLY", "XLE", "XLU",  # ETFs
            "AAPL", "MSFT", "TSLA", "NVDA", "META",  # Mega cap
            "AMZN", "GOOGL", "GOOG", "BRK", "NFLX"  # Large cap
        ]

        self._load_metadata()

    def _load_metadata(self):
        """Load metadata about previous downloads"""
        self.metadata = {}
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file) as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load metadata: {e}")
                self.metadata = {}

    def save_metadata(self):
        """Save metadata about downloads"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: Could not save metadata: {e}")

    def get_data_path(self, symbol: str, data_type: str = None) -> Path:
        """Get path for storing option data"""
        if data_type is None:
            data_type = self.data_type

        path = self.data_dir / "direct_api" / data_type / symbol
        path.mkdir(parents=True, exist_ok=True)
        return path

    def __repr__(self):
        return (
            f"DirectAPIConfig(api={self.api_base_url}, "
            f"data_type={self.data_type}, "
            f"data_dir={self.data_dir})"
        )


class LocalDaemonConfig:
    """Configuration for ThetaTerminal local daemon (EOD data only)"""

    def __init__(self):
        # ThetaTerminal daemon connection
        self.theta_host = "127.0.0.1"
        self.theta_port = 25503
        self.theta_base_url = f"http://{self.theta_host}:{self.theta_port}"
        self.timeout = 180  # API can be slow for large date ranges

        # Data storage
        self.data_dir = Path.home() / "data" / "thetadata"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Metadata file for tracking downloads
        self.metadata_file = self.data_dir / "metadata_local_daemon.json"

        # API retry configuration
        self.max_retries = 3
        self.retry_delay = 5  # seconds

        # Download configuration
        self.max_workers = 1  # Serial downloads (daemon max concurrent is 2)
        self.batch_size = 50  # Symbols per batch
        self.request_delay = 1.0  # Delay between requests in seconds

        # Option symbols to download
        self.option_symbols = [
            "SPY", "QQQ", "IWM", "XLF", "XLV", "XLY", "XLE", "XLU",  # ETFs
            "AAPL", "MSFT", "TSLA", "NVDA", "META",  # Mega cap
            "AMZN", "GOOGL", "GOOG", "BRK", "NFLX"  # Large cap
        ]

        self._load_metadata()

    def _load_metadata(self):
        """Load metadata about previous downloads"""
        self.metadata = {}
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file) as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load metadata: {e}")
                self.metadata = {}

    def save_metadata(self):
        """Save metadata about downloads"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: Could not save metadata: {e}")

    def get_data_path(self, symbol: str, expiration: str = None) -> Path:
        """Get path for storing option data"""
        path = self.data_dir / "local_daemon" / "eod" / symbol
        path.mkdir(parents=True, exist_ok=True)

        if expiration:
            return path / f"{expiration}.parquet"
        return path

    def __repr__(self):
        return (
            f"LocalDaemonConfig(host={self.theta_host}, port={self.theta_port}, "
            f"data_dir={self.data_dir})"
        )
