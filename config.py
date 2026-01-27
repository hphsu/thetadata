"""
Configuration management for ThetaData downloader
Centralizes all settings and configuration
"""
import os
from pathlib import Path
from datetime import datetime
import json

class Config:
    """Configuration for ThetaTerminal daemon connection and data storage"""

    def __init__(self):
        # ThetaTerminal daemon connection
        self.theta_host = "127.0.0.1"
        self.theta_port = 25503  # Default port, can be auto-updated
        self.theta_base_url = f"http://{self.theta_host}:{self.theta_port}"
        self.timeout = 180  # API can be slow for large date ranges (increased for large EOD queries)

        # Data storage
        self.data_dir = Path.home() / "data" / "thetadata"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Metadata file for tracking downloads
        self.metadata_file = self.data_dir / "metadata.json"

        # Asset types configuration
        self.asset_types = {
            "options": {
                "enabled": True,
                "description": "Option contracts",
            }
        }

        # API retry configuration
        self.max_retries = 3
        self.retry_delay = 5  # seconds

        # Download configuration
        self.max_workers = 1  # Serial downloads (daemon max concurrent is 2, reduced for stability)
        self.batch_size = 50  # Symbols per batch
        self.request_delay = 1.0  # Delay between requests in seconds (throttle to daemon limits)

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

    def get_last_update(self, asset_type: str, symbol: str = None) -> datetime:
        """Get last update timestamp for an asset"""
        key = f"{asset_type}"
        if symbol:
            key += f"_{symbol}"

        if key in self.metadata and self.metadata[key]:
            try:
                return datetime.fromisoformat(self.metadata[key])
            except:
                return None
        return None

    def set_last_update(self, asset_type: str, symbol: str = None, timestamp: datetime = None):
        """Set last update timestamp"""
        if timestamp is None:
            timestamp = datetime.now()

        key = f"{asset_type}"
        if symbol:
            key += f"_{symbol}"

        self.metadata[key] = timestamp.isoformat()
        self.save_metadata()

    def get_data_path(self, asset_type: str, symbol: str = None) -> Path:
        """Get path for storing asset data"""
        path = self.data_dir / asset_type
        path.mkdir(parents=True, exist_ok=True)

        if symbol:
            return path / f"{symbol}.parquet"
        return path

    def __repr__(self):
        return (
            f"Config(host={self.theta_host}, port={self.theta_port}, "
            f"data_dir={self.data_dir})"
        )
