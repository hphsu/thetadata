"""
Test the correct minute-level endpoint: /v3/option/history/ohlc
This is the endpoint documented for minute-level data on local daemon
"""
import requests
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:25503"
TIMEOUT = 30

def test_ohlc_endpoint():
    """Test the /v3/option/history/ohlc endpoint with various intervals"""

    print("\n" + "="*70)
    print("TESTING /v3/option/history/ohlc ENDPOINT")
    print("="*70)
    print(f"Base URL: {BASE_URL}")

    # Test parameters
    symbol = "SPY"

    # Get a recent expiration first
    print("\n1. Getting available expirations...")
    try:
        resp = requests.get(
            f"{BASE_URL}/v3/option/list/expirations",
            params={"symbol": symbol, "format": "json"},
            timeout=TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "response" in data:
                expirations = [item["expiration"] for item in data["response"]]
                # Find the next weekly expiration (within 7 days)
                today = datetime.now()
                for exp in expirations:
                    exp_date = datetime.strptime(exp, "%Y-%m-%d")
                    if exp_date > today and (exp_date - today).days <= 14:
                        expiration = exp.replace("-", "")
                        print(f"   Using expiration: {expiration}")
                        break
                else:
                    expiration = expirations[0].replace("-", "") if expirations else "20260131"
                    print(f"   Using first expiration: {expiration}")
            else:
                expiration = "20260131"
                print(f"   Using default: {expiration}")
        else:
            expiration = "20260131"
            print(f"   Using default: {expiration}")
    except Exception as e:
        expiration = "20260131"
        print(f"   Error getting expirations: {e}")
        print(f"   Using default: {expiration}")

    # Test different intervals
    intervals = [
        ("1m", "1-minute bars"),
        ("5m", "5-minute bars"),
        ("15m", "15-minute bars"),
        ("1h", "1-hour bars"),
        ("1s", "1-second bars (sub-minute)"),
    ]

    # Use today and yesterday for date range
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    # For single-day test (required for sub-minute intervals)
    single_date = yesterday.strftime("%Y%m%d")

    print(f"\n2. Testing OHLC endpoint with various intervals...")
    print(f"   Symbol: {symbol}")
    print(f"   Expiration: {expiration}")
    print(f"   Date: {single_date}")

    results = []

    for interval, description in intervals:
        print(f"\n   Testing interval={interval} ({description})...")

        try:
            params = {
                "symbol": symbol,
                "expiration": expiration,
                "strike": "*",  # All strikes
                "right": "both",
                "interval": interval,
                "date": single_date,  # Single day for sub-minute support
                "format": "json"
            }

            resp = requests.get(
                f"{BASE_URL}/v3/option/history/ohlc",
                params=params,
                timeout=TIMEOUT
            )

            status = resp.status_code

            if status == 200:
                data = resp.json()
                if isinstance(data, dict) and "response" in data:
                    rows = len(data["response"])
                    if rows > 0:
                        print(f"   ✅ SUCCESS: {rows:,} rows returned")
                        sample = data["response"][0]
                        print(f"      Sample: {sample.get('symbol')} {sample.get('strike')} {sample.get('right')} @ {sample.get('timestamp')}")
                        results.append((interval, "SUCCESS", rows))
                    else:
                        print(f"   ⚠️  Empty response (no data for this date)")
                        results.append((interval, "NO_DATA", 0))
                elif isinstance(data, list):
                    print(f"   ✅ SUCCESS: {len(data):,} rows returned")
                    results.append((interval, "SUCCESS", len(data)))
                else:
                    print(f"   ⚠️  Unexpected response format: {type(data)}")
                    results.append((interval, "UNEXPECTED", 0))
            elif status == 404:
                print(f"   ❌ NOT FOUND (endpoint doesn't exist)")
                results.append((interval, "NOT_FOUND", 0))
            elif status == 472:
                print(f"   ❌ SUBSCRIPTION ERROR (requires higher tier)")
                results.append((interval, "SUBSCRIPTION", 0))
            elif status == 400:
                print(f"   ❌ BAD REQUEST: {resp.text[:100]}")
                results.append((interval, "BAD_REQUEST", 0))
            else:
                print(f"   ⚠️  HTTP {status}: {resp.text[:100]}")
                results.append((interval, f"HTTP_{status}", 0))

        except requests.exceptions.Timeout:
            print(f"   ⏱️  TIMEOUT")
            results.append((interval, "TIMEOUT", 0))
        except Exception as e:
            print(f"   ❌ ERROR: {str(e)[:50]}")
            results.append((interval, "ERROR", 0))

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    success_intervals = [r for r in results if r[1] == "SUCCESS"]
    subscription_blocked = [r for r in results if r[1] == "SUBSCRIPTION"]

    if success_intervals:
        print("\n✅ MINUTE-LEVEL DATA IS AVAILABLE!")
        print("   Working intervals:")
        for interval, status, rows in success_intervals:
            print(f"      - {interval}: {rows:,} rows")

    if subscription_blocked:
        print("\n⚠️  Some intervals blocked by subscription:")
        for interval, status, _ in subscription_blocked:
            print(f"      - {interval}: Requires Standard or Pro tier")

    if not success_intervals and not subscription_blocked:
        # Check if endpoint exists at all
        not_found = [r for r in results if r[1] == "NOT_FOUND"]
        if not_found:
            print("\n❌ Endpoint /v3/option/history/ohlc not found")
            print("   Your ThetaTerminal version may not support this endpoint")
        else:
            print("\n⚠️  No minute-level data available")
            print("   Check your subscription tier at https://app.thetadata.us")

    # Check subscription info
    print("\n" + "="*70)
    print("SUBSCRIPTION INFO")
    print("="*70)
    print("\nEndpoint requirements from documentation:")
    print("  /v3/option/history/ohlc   → Standard or Pro tier")
    print("  /v3/option/history/quote  → VALUE, Standard, or Pro tier")
    print("  /v3/option/history/trade  → Standard or Pro tier")
    print("  /v3/option/history/eod    → VALUE, Standard, or Pro tier")
    print("  /v3/option/snapshot/quote → Standard or Pro tier (real-time)")

    return results


if __name__ == "__main__":
    test_ohlc_endpoint()
