# Setup Guide: Downloading Minute-Level Option Data

## The Discovery

Your feature list showed "1 minute intervals" available, which refers to the **ThetaData Direct API**, not the local ThetaTerminal daemon.

- **Local Daemon** (port 25503): EOD data only ❌
- **Direct API** (api.thetadata.us): Minute-level data ✅

## Step 1: Get Your API Key

### Method A: Web Interface (Recommended)
1. Go to https://app.thetadata.us/account/api
2. Log in with your ThetaData account
3. Create an API key if you don't have one
4. Copy your API key (looks like: `abc123def456ghi789`)

### Method B: Check Existing Keys
If you already created a key but can't find it:
1. Log in to https://app.thetadata.us
2. Click Account → API Keys
3. Copy the key shown there

## Step 2: Set API Key in Environment

### On macOS/Linux:
```bash
# Add to your shell profile (~/.zshrc, ~/.bash_profile, etc)
export THETADATA_API_KEY='your_actual_key_here'

# Then reload your shell
source ~/.zshrc
```

### Verify it worked:
```bash
echo $THETADATA_API_KEY
# Should print your key
```

## Step 3: Test Direct API Connection

```bash
cd ~/src/thetadata
python test_direct_api.py
```

Expected output if configured correctly:
```
DIRECT THETADATA API TEST
API Key found: abc123def4...

Testing: /option/quote?root=SPY&...
  Result: ✅ AVAILABLE with data

Testing: /option/history/minute?root=SPY&...
  Result: ✅ AVAILABLE with data
```

## Step 4: Download Minute-Level Data

```bash
python downloader_minute_api.py
```

This will:
1. Validate your API key
2. Download 30 days of minute-level option data
3. Store in: `~/data/thetadata/direct_api/minute/{symbol}/`
4. Save as Parquet files for VectorBT backtesting

## Understanding the Data Structure

### Files Downloaded
```
~/data/thetadata/direct_api/minute/
├── SPY/
│   ├── SPY_20250131_400.0_C.parquet    (Call at 400 strike)
│   ├── SPY_20250131_400.0_P.parquet    (Put at 400 strike)
│   └── ... more contracts
├── QQQ/
│   ├── QQQ_20250131_350.0_C.parquet
│   └── ... more contracts
```

### Data Format
Each Parquet file contains minute-level OHLCV data:
- **time**: Timestamp of minute
- **open**: Opening price
- **high**: High price in minute
- **low**: Low price in minute
- **close**: Closing price
- **volume**: Trading volume in contracts
- **bid**: Bid price
- **ask**: Ask price

## Configuration Options

Edit `downloader_minute_api.py` or `config_direct_api.py` to adjust:

```python
self.lookback_days = 30        # How many days of data to download
self.max_workers = 2           # Parallel downloads (2-4 recommended)
self.data_type = "minute"      # or "daily", "tick"
self.option_symbols = [...]    # Which symbols to download
```

## Troubleshooting

### Error: "No API key found"
```bash
# Solution: Set the environment variable
export THETADATA_API_KEY='your_key'

# Verify it's set
echo $THETADATA_API_KEY
```

### Error: "401 Unauthorized"
```bash
# Your API key is invalid or has expired
# 1. Check key has no extra spaces
# 2. Verify key at https://app.thetadata.us/account/api
# 3. Generate a new key if needed
```

### Error: "404 Not Found"
- API endpoint may have changed
- Or no data available for that contract
- This is normal for some contracts

### Error: "429 Too Many Requests"
- You've exceeded rate limits
- Solution: Reduce `max_workers` to 1-2
- Or: Reduce number of symbols
- Wait a few minutes and try again

### Slow Downloads
- Direct API is still slower than expected
- Normal: 50-200 rows per second
- If slower: Check internet connection

## Using Downloaded Data with VectorBT

```python
import pandas as pd
import vectorbt as vbt
from pathlib import Path

# Load minute-level data
data_dir = Path.home() / "data" / "thetadata" / "direct_api" / "minute"

# Example: Load SPY 400 call data
spy_400c = pd.read_parquet(data_dir / "SPY" / "SPY_20250131_400.0_C.parquet")

# Resample to daily or hourly
spy_daily = spy_400c.set_index('time').resample('D')[['open', 'high', 'low', 'close', 'volume']].ohlc()

# Create VectorBT portfolio
# ... your backtesting code here
```

## What's Different from EOD Downloader?

| Aspect | EOD Daemon | Minute API |
|--------|-----------|-----------|
| Setup | Just run | Need API key |
| Speed | Slow (3+ min/contract) | Fast (seconds) |
| Data granularity | Daily OHLC | Minute OHLC |
| Coverage | Limited symbols | All symbols |
| Real-time | ❌ No | ✅ Yes |
| File size | Smaller | Larger |

## Next Steps

1. ✅ Get API key
2. ✅ Set environment variable
3. ✅ Test with `test_direct_api.py`
4. ✅ Download minute data with `downloader_minute_api.py`
5. ✅ Use data in VectorBT for backtesting

## Questions?

- ThetaData API Docs: https://docs.thetadata.us
- Account & API Keys: https://app.thetadata.us/account/api
- Status Page: https://status.thetadata.us/
