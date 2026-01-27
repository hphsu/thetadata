# ThetaData Option Downloader

Download historical option data using ThetaTerminal v3 local daemon. Store efficiently in Parquet format for backtesting with VectorBT.

## Features

- ✅ **Automatic daemon detection and startup** - Connects to local ThetaTerminal or starts it automatically
- ✅ **Bulk option data download** - Downloads all available option expirations for thousands of symbols
- ✅ **Efficient storage** - Parquet compression reduces storage by 80-90%
- ✅ **Incremental updates** - Only downloads new data, doesn't re-fetch old data
- ✅ **Parallel processing** - Downloads multiple symbols concurrently
- ✅ **Metadata tracking** - Remembers what's been downloaded to avoid duplicates
- ✅ **VectorBT ready** - Data format optimized for backtesting

## Requirements

- **ThetaTerminal v3** running locally (Java 21+)
- **ThetaData subscription** with OPTIONS access (VALUE plan or higher)
- **Python 3.8+** with pandas, pyarrow

## Installation

```bash
# 1. Ensure ThetaTerminalv3.jar is in one of these locations:
#    - Current directory
#    - ~/Downloads
#    - ~/Desktop
#    - Project directory

# 2. Install Python dependencies
pip install pandas pyarrow requests

# 3. Verify setup
cd ~/src/thetadata
python test_download.py
```

## Quick Start

### Test First (verify everything works)
```bash
python test_download.py
```

Output shows:
- Daemon connection status
- Available symbols (15,000+)
- Sample download (2,300+ records)
- Storage verification

### Full Download
```bash
# Download all available data
python downloader.py

# Expected: 30 minutes to 2 hours depending on network and CPU
```

### View Results
```bash
ls -lh ~/data/thetadata/options/
# SPY/  QQQ/  IWM/  ...
```

## API Details

### Supported Endpoints
- **List Symbols**: `/v3/option/list/symbols` - Get all symbols with options
- **List Expirations**: `/v3/option/list/expirations?symbol=SPY` - Get available expirations
- **Historical EOD**: `/v3/option/history/eod` - End-of-day option bars

### API Constraints
- Maximum **365 days** per query
- VALUE subscription supports **options only**
- Expirations available: **1969 for SPY**, varying for other symbols
- Response structure: **nested by contract** (strike, right, expiration)

### Data Format
```
{
  "strike": 380.0,
  "right": "CALL",
  "expiration": "2026-02-20",
  "symbol": "SPY",
  "open": 15.4,
  "high": 16.2,
  "low": 15.1,
  "close": 15.8,
  "volume": 1250,
  "bid": 15.65,
  "ask": 15.75,
  ...
}
```

## Configuration

Edit `config.py` to customize:
- `theta_host` / `theta_port` - ThetaTerminal connection
- `data_dir` - Where to store downloaded data
- `max_workers` - Parallel download threads
- `timeout` - API request timeout (currently 120s)

## Usage Examples

### Download specific symbols only
```python
from downloader import OptionDownloader

downloader = OptionDownloader()
downloader.download_option_symbol("SPY")  # Download one symbol
```

### Load and use data
```python
import pandas as pd
from pathlib import Path

# Load option data
path = Path.home() / "data/thetadata/options/SPY/eod_20260131.parquet"
df = pd.read_parquet(path)

# Filter by right (calls or puts)
calls = df[df['right'] == 'CALL']
puts = df[df['right'] == 'PUT']

# Use with VectorBT
import vectorbt as vbt
# ... create strategy using df
```

### Schedule daily updates
```bash
python scheduler.py
# Runs at 2:00 AM daily
# Only downloads new data since last run
```

## Storage Structure

```
~/data/thetadata/
├── options/
│   ├── SPY/
│   │   ├── eod_20260127.parquet    (2.3 MB)
│   │   ├── eod_20260131.parquet    (1.8 MB)
│   │   └── ...
│   ├── QQQ/
│   │   ├── eod_20260127.parquet
│   │   └── ...
│   └── ...
├── metadata.json                   (tracks last updates)
└── README.md                        (this file)
```

## Troubleshooting

### "Daemon not running"
```bash
# Start ThetaTerminal manually
java -jar ~/Downloads/ThetaTerminalv3.jar
```

### "No data found for symbol X"
- Symbol might not have VALUE subscription support
- Some symbols require STANDARD plan
- Check logs for specific error messages

### Timeout errors
- API is slow for large date ranges
- Try downloading fewer symbols
- Increase `timeout` in config.py

### Out of memory
- Reduce `max_workers` in config.py
- Download symbols in smaller batches

## Architecture

```
ThetaTerminal v3 (Java daemon)
    ↓ HTTP REST API
ThetaDataClient (API wrapper)
    ↓
OptionDownloader (orchestrator)
    ├→ DaemonManager (lifecycle)
    ├→ DataManager (Parquet storage)
    └→ ThreadPoolExecutor (parallel downloads)
    ↓
~/data/thetadata/ (Parquet files)
    ↓
VectorBT (backtesting)
```

## Performance Notes

- **Download speed**: 15,000 symbols with ~1,969 expirations each
  - Time: 2-8 hours depending on network
  - Network bandwidth: ~500 MB - 2 GB total

- **Storage**:
  - Raw API: 200 GB (estimated)
  - Parquet compressed: 20-50 GB
  - Compression ratio: 80-90%

- **Retrieval speed**:
  - Load SPY all expirations: <100ms
  - Query range: <50ms

## API Versions

This downloader uses **ThetaTerminal v3 HTTP REST API**:
- Endpoint base: `http://127.0.0.1:25503/v3/`
- Parameters: snake_case (`start_date`, `end_date`)
- Authentication: Local daemon (no API key needed)
- Response: JSON format

## Support

For detailed troubleshooting and issue explanations, see `TROUBLESHOOTING_SOLVED.md`.

For quick reference, see `QUICKSTART.md`.

## License

Use only for permitted backtesting and analysis as per ThetaData terms.
