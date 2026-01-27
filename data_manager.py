"""
Data manager for storing and retrieving option data in Parquet format
Handles incremental updates and efficient storage
"""
import logging
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class ParquetDataManager:
    """Manage option data storage in Parquet format"""

    def __init__(self, config):
        self.config = config
        self.data_dir = config.data_dir

    def save_option_data(
        self,
        symbol: str,
        expiration: str,
        data: List[Dict],
        mode: str = "append"
    ) -> bool:
        """
        Save option data to Parquet file
        symbol: underlying symbol (SPY, QQQ, etc)
        expiration: contract expiration (YYYYMMDD format)
        data: list of OHLC records
        mode: "append" or "overwrite"
        """
        try:
            if not data:
                logger.debug(f"No data to save for {symbol} exp={expiration}")
                return False

            # Convert to DataFrame
            df = pd.DataFrame(data)

            # Ensure required columns exist
            required_cols = ["timestamp", "open", "high", "low", "close"]
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"Missing columns: {missing_cols}. Proceeding anyway.")

            # Add metadata columns
            df["symbol"] = symbol
            df["expiration"] = expiration
            df["created_at"] = datetime.now()

            # Determine file path
            options_dir = self.data_dir / "options" / symbol
            options_dir.mkdir(parents=True, exist_ok=True)
            file_path = options_dir / f"eod_{expiration}.parquet"

            # Save or append
            if mode == "append" and file_path.exists():
                existing_df = pd.read_parquet(file_path)

                # Remove duplicate timestamps
                df = df[~df["timestamp"].isin(existing_df["timestamp"])]

                if len(df) > 0:
                    combined_df = pd.concat([existing_df, df], ignore_index=True)
                    combined_df = combined_df.sort_values("timestamp").drop_duplicates("timestamp")
                    combined_df.to_parquet(file_path, compression="snappy")
                    logger.info(f"Appended {len(df)} records to {file_path.name}")
                    return True
                else:
                    logger.debug(f"No new data to append for {symbol} exp={expiration}")
                    return True
            else:
                df.to_parquet(file_path, compression="snappy")
                logger.info(f"Saved {len(df)} records to {file_path.name}")
                return True

        except Exception as e:
            logger.error(f"Failed to save option data for {symbol} exp={expiration}: {e}")
            return False

    def load_option_data(
        self,
        symbol: str,
        expiration: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """
        Load option data from Parquet file
        Optionally filter by date range
        """
        try:
            options_dir = self.data_dir / "options" / symbol
            file_path = options_dir / f"eod_{expiration}.parquet"

            if not file_path.exists():
                logger.debug(f"No data file found for {symbol} exp={expiration}")
                return None

            df = pd.read_parquet(file_path)

            # Filter by date range if specified
            if start_date or end_date:
                df["date"] = pd.to_datetime(df["timestamp"]).dt.date

                if start_date:
                    start = pd.to_datetime(start_date).date()
                    df = df[df["date"] >= start]

                if end_date:
                    end = pd.to_datetime(end_date).date()
                    df = df[df["date"] <= end]

                df = df.drop("date", axis=1)

            logger.debug(f"Loaded {len(df)} records for {symbol} exp={expiration}")
            return df

        except Exception as e:
            logger.error(f"Failed to load option data for {symbol} exp={expiration}: {e}")
            return None

    def get_symbol_stats(self, asset_type: str = "options") -> Optional[Dict]:
        """
        Get statistics about stored data
        Returns dict of {symbol: {rows, file_size_mb, start_date, end_date, expirations}}
        """
        try:
            stats = {}
            asset_dir = self.data_dir / asset_type

            if not asset_dir.exists():
                return stats

            # Iterate through symbols
            for symbol_dir in asset_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue

                symbol = symbol_dir.name
                total_rows = 0
                total_size = 0
                all_dates = []
                expirations = []

                # Check all expiration files
                for file_path in symbol_dir.glob("eod_*.parquet"):
                    try:
                        df = pd.read_parquet(file_path)
                        total_rows += len(df)
                        total_size += file_path.stat().st_size

                        if "timestamp" in df.columns:
                            all_dates.extend(df["timestamp"].tolist())

                        # Extract expiration from filename: eod_20260131.parquet
                        exp = file_path.stem.replace("eod_", "")
                        expirations.append(exp)

                    except Exception as e:
                        logger.debug(f"Error reading {file_path}: {e}")
                        continue

                if total_rows > 0:
                    all_dates.sort()
                    stats[symbol] = {
                        "rows": total_rows,
                        "file_size_mb": total_size / (1024 * 1024),
                        "start_date": str(all_dates[0]) if all_dates else "N/A",
                        "end_date": str(all_dates[-1]) if all_dates else "N/A",
                        "expirations": expirations,
                        "expiration_count": len(expirations)
                    }

            return stats

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return None

    def get_latest_timestamp(self, symbol: str, expiration: str) -> Optional[datetime]:
        """Get timestamp of most recent data for incremental updates"""
        try:
            options_dir = self.data_dir / "options" / symbol
            file_path = options_dir / f"eod_{expiration}.parquet"

            if not file_path.exists():
                return None

            df = pd.read_parquet(file_path)
            if len(df) > 0 and "timestamp" in df.columns:
                return df["timestamp"].max()

            return None

        except Exception as e:
            logger.debug(f"Failed to get latest timestamp: {e}")
            return None
