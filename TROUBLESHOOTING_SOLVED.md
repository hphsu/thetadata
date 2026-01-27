# ThetaData API Troubleshooting - RESOLVED

## Summary of Issues and Solutions

### Issue 1: Port Conflicts (v3 API returning 404)
**Problem:** Multiple daemon instances running, causing port conflicts and API not accessible.
**Root Cause:** Previous daemon startup attempts left zombie processes bound to ports 25503 and 25520.
**Solution:**
- Killed all ThetaTerminal processes (`pkill -9`)
- Started fresh daemon instance
- Verified port 25503 is free before startup

### Issue 2: Deprecated API Parameter Names
**Problem:** API returning 410 "Gone" errors with v2 endpoints, requesting upgrade to v3.
**Root Cause:** API v2 endpoints are deprecated; needed v3 parameter names.
**Solution:**
- Updated from `root` → `symbol` parameter
- Updated from `start_date` → `startDate` (camelCase) - WAIT, actually uses `start_date` (snake_case)
- Updated endpoint paths from `/v2/hist/*` → `/v3/history/*` (note: "history" not "hist")

### Issue 3: Stock Data Requires VALUE Subscription
**Problem:** Stock data requests returning 403 Forbidden.
**Root Cause:** User's VALUE plan only covers OPTIONS data, not STOCK data.
**Solution:**
- Focus on option data downloads exclusively
- Stock data would require STANDARD or higher subscription

### Issue 4: API Response Format Mismatch
**Problem:** Expected simple OHLC bars, API returned nested contract structure.
**Root Cause:** Option EOD endpoint returns data grouped by contract (strike + right + expiration).
**Solution:**
- Updated parser to flatten nested response structure
- Each bar now includes contract metadata (strike, right, expiration, symbol)

### Issue 5: 365-Day Maximum Date Range
**Problem:** Requests with date ranges > 365 days returning 500 Server Error.
**Root Cause:** API limit imposed on maximum queryable date range.
**Solution:**
- Added date range validation in client
- Automatically truncates ranges exceeding 365 days
- Default to 364 days lookback for safety

### Issue 6: API Request Timeouts
**Problem:** Requests for large date ranges timing out at 30 seconds.
**Root Cause:** API is slow when returning thousands of contracts across full 365-day range.
**Solution:**
- Increased timeout from 30s to 120s
- Test uses smaller 30-day windows for verification
- Production can adjust based on needs

### Issue 7: Expired Expiration Dates
**Problem:** Tests trying to download data for past expirations (Jan 2, 2025) when today is Jan 27, 2026.
**Root Cause:** Test logic wasn't accounting for date progression.
**Solution:**
- Updated test to find first future expiration
- Only download data for expirations >= today

## What Works Now

✅ **API Connection**
- ThetaTerminal v3 HTTP REST API accessible on port 25503
- v3 endpoints: `/v3/option/list/symbols`, `/v3/option/list/expirations`, `/v3/option/history/eod`

✅ **Data Download**
- Successfully downloading option EOD data
- Tested: SPY 2026-01-27 expiration (2,306 records downloaded)
- Data includes: strikes, calls/puts, open, high, low, close, volume, bid/ask, etc.

✅ **Storage**
- Parquet format compression working
- Data successfully saved and retrieved
- Metadata tracking functional

✅ **Parallel Processing**
- ThreadPoolExecutor ready for downloading multiple symbols/expirations concurrently

## Next Steps

### For Full Production Download:
```bash
# Run the full downloader
python downloader.py

# Or if limited to certain symbols:
python downloader.py --limit 10  # Download first 10 symbols
```

### Data Location:
```
~/data/thetadata/
├── options/
│   ├── SPY/
│   │   ├── eod_20260127.parquet
│   │   ├── eod_20260131.parquet
│   │   └── ...
│   ├── QQQ/
│   └── ...
└── metadata.json
```

### Key Limitations to Remember:
1. **VALUE plan** covers options only (not stocks/futures/crypto)
2. **365-day maximum** for any single API query
3. **API is slow** for large contracts*days combinations
4. **~15,000 symbols** with options available
5. **Daily use** recommended via scheduler for incremental updates

## Files Modified:
- `thetadata_client.py` - Corrected v3 API endpoints and response parsing
- `config.py` - Increased timeout to 120s
- `test_download.py` - Fixed date logic and expiration selection
- `downloader.py` - Added Dict import

## Testing Status:
✅ All 4 tests passing:
1. Daemon connection
2. Symbol retrieval (15,130 symbols found)
3. Sample data download (2,306 records for SPY)
4. Parquet storage and retrieval
