# ThetaData APIs: Local Daemon vs Direct API

## Quick Summary

You have **TWO different APIs** available. Your feature list showing "1 minute intervals" refers to the **Direct API**, not the local daemon.

| Feature | Local Daemon | Direct API |
|---------|-------------|-----------|
| **Data Type** | End-of-Day (EOD) | Minute, Daily, Tick |
| **Real-time** | ❌ No | ✅ Yes |
| **URL** | http://127.0.0.1:25503 | https://api.thetadata.us |
| **Auth** | Subscription-based | API Key required |
| **Rate Limit** | 2 concurrent requests | Higher |
| **Speed** | Slow (3+ min/request) | Fast |
| **Expirations per symbol** | 600-1500 | All available |

## What You Currently Have

### Local ThetaTerminal Daemon (Port 25503)
- ✅ Supports: `/option/list/symbols`, `/option/list/expirations`, `/option/history/eod`
- ❌ Does NOT support: minute-level, real-time, quotes
- Why it's slow: Processing 1000+ contracts per request with 364-day history
- Best for: Occasional batch updates of EOD data

### ThetaData Direct API (api.thetadata.us)
- ✅ Supports: minute-level, daily, tick, real-time quotes, chains
- ❌ Does NOT support: local daemon (no network access needed)
- Requires: API key from https://app.thetadata.us/account/api
- Best for: High-frequency data, minute-level analysis, real-time updates

## Why Your Download Failed

The local daemon EOD endpoint was failing because:
1. Each request processes 1000+ option contracts
2. Each contract needs 364 days of data
3. Backend processing is computationally expensive
4. Daemon timeout (180s) was too short
5. You received HTTP 472 errors (subscription limitations)

## Getting Minute-Level Data

### Step 1: Get Your API Key
1. Go to https://app.thetadata.us/account/api
2. Create or copy your API key
3. Run:
```bash
export THETADATA_API_KEY='your_actual_key_here'
```

### Step 2: Test Direct API
```bash
python test_direct_api.py
```

### Step 3: Download Minute-Level Data
```bash
python downloader_minute_api.py
```

## Configuration Files

### Local Daemon (EOD Data)
```python
from config import Config
config = Config()
# Uses: http://127.0.0.1:25503/v3/option/history/eod
```

### Direct API (Minute Data)
```python
from config_direct_api import DirectAPIConfig
config = DirectAPIConfig()
# Uses: https://api.thetadata.us/option/history/minute
```

## API Endpoints Comparison

### Available on Local Daemon
```
GET /v3/option/list/symbols           → Available
GET /v3/option/list/expirations       → Available
GET /v3/option/history/eod            → Available (SLOW, sometimes fails)
GET /v3/option/history/minute         → ❌ NOT FOUND
GET /v3/option/quote                  → ❌ NOT FOUND
```

### Available on Direct API
```
GET /option/history/minute            → ✅ Available
GET /option/history/daily             → ✅ Available
GET /option/quote                     → ✅ Available
GET /option/quotes                    → ✅ Available (real-time)
GET /option/chains                    → ✅ Available
GET /option/expirations               → ✅ Available
```

## Recommendations

### Use Local Daemon If:
- You want to avoid API key management
- You only need EOD data
- You have limited API request quota
- You prefer local caching

### Use Direct API If:
- You need minute-level data ✓
- You need real-time updates
- You want faster response times
- You want more flexibility

## File Structure

### EOD Data (Local Daemon)
```
~/data/thetadata/
├── local_daemon/
│   ├── eod/
│   │   ├── SPY/
│   │   │   └── 20250131.parquet
```

### Minute Data (Direct API)
```
~/data/thetadata/
├── direct_api/
│   ├── minute/
│   │   ├── SPY/
│   │   │   ├── SPY_20250131_400.0_C.parquet
│   │   │   ├── SPY_20250131_400.0_P.parquet
```

## Error Codes Reference

### Local Daemon
- `410 Gone`: API endpoint deprecated (v2 endpoints)
- `472 Client Error`: Symbol not available on subscription tier
- `Read timed out (180)`: Endpoint too slow, increase timeout

### Direct API
- `401 Unauthorized`: Invalid or missing API key
- `404 Not Found`: No data available for request
- `429 Too Many Requests`: Rate limit exceeded

## Next Steps

1. **Get API Key**: https://app.thetadata.us/account/api
2. **Test Connection**: `export THETADATA_API_KEY='...' && python test_direct_api.py`
3. **Download Minute Data**: `python downloader_minute_api.py`
4. **Use in Backtesting**: Minute data will be in `~/data/thetadata/direct_api/minute/{symbol}/`

## Documentation

- Local Daemon API: https://docs.thetadata.us/operations/option_list_symbols.html
- Direct API: https://docs.thetadata.us/
- API Key Management: https://app.thetadata.us/account/api
