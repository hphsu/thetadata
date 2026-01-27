# ThetaData Option Downloader - Quick Start

## What You Have
✅ ThetaTerminal v3.jar running locally at `http://127.0.0.1:25503`
✅ VALUE subscription (supports OPTIONS data)
✅ Python scripts ready to download and store option data

## Quick Test (2 minutes)
```bash
cd ~/src/thetadata
python test_download.py
```

Expected output:
```
✓ ThetaTerminal daemon is running
✓ Successfully retrieved 15,130 option symbols
✓ Downloaded sample option data (2,306 records)
✓ Successfully saved to Parquet
```

## Start Full Download (can take hours)
```bash
python downloader.py
```

This will:
1. Verify ThetaTerminal is running (auto-start if needed)
2. Get all available option symbols (15,000+)
3. Download all available expirations for each symbol
4. Save to `~/data/thetadata/options/`
5. Show summary of downloaded data

## View Downloaded Data
```bash
ls -lh ~/data/thetadata/options/
# Example output:
# SPY/
#   eod_20260127.parquet (100 KB)
#   eod_20260131.parquet (150 KB)
#   ...
```

## Use in VectorBT
```python
import pandas as pd
from pathlib import Path

# Load option data
data_dir = Path.home() / "data" / "thetadata" / "options"
spy_data = pd.read_parquet(data_dir / "SPY" / "eod_20260127.parquet")

print(spy_data.head())
# Columns: strike, right, expiration, symbol, open, high, low, close, volume, ...

# Use with VectorBT for backtesting
```

## Key Limitations
- **VALUE plan**: Options only (no stocks, futures, or crypto)
- **Date range**: Maximum 365 days per API query
- **Symbols**: ~15,000 with available options
- **API rate**: Slow for large downloads (120s timeout)

## Troubleshooting

### Daemon not starting
```bash
# Check if Java is installed
java -version

# Start manually in another terminal
cd ~/Downloads
java -jar ThetaTerminalv3.jar
```

### Timeout errors
- API is slow for large date ranges
- Try downloading smaller symbols first
- Consider splitting downloads by date range

### No data for a symbol
- Symbol might not have VALUE subscription access
- Check logs for specific errors
- Some symbols are restricted to STANDARD plans

## Files Created
```
~/src/thetadata/
├── config.py               # Configuration management
├── thetadata_client.py     # API client (v3 endpoints)
├── data_manager.py         # Parquet storage
├── daemon_manager.py       # Daemon lifecycle
├── downloader.py           # Main download script
├── test_download.py        # Verification tests
└── QUICKSTART.md          # This file

~/data/thetadata/
├── options/               # Downloaded option data
├── metadata.json         # Track last updates
└── README.md            # Data documentation
```

## For Daily Updates
Set up the scheduler (see scheduler.py):
```bash
# Runs daily at 2:00 AM
python scheduler.py
```

This incrementally updates your data with latest available prices without re-downloading old data.

## Questions?
See TROUBLESHOOTING_SOLVED.md for detailed issue explanations.
