"""
Test script to check if minute-level option data endpoints are available
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:25503"
TIMEOUT = 30

def test_endpoints():
    """Test various option data endpoints to find what's available"""

    # Test parameters
    symbol = "SPY"
    expiration = "20260131"  # Next Friday

    # List of potential endpoints to test
    endpoints = [
        # Minute-level endpoints
        ("/v3/option/history/minute", "Minute-level history"),
        ("/v3/option/history/tick", "Tick-level history"),
        ("/v3/option/history/intraday", "Intraday history"),
        ("/v3/option/history/bars", "Minute bars"),

        # Quote endpoints
        ("/v3/option/quote", "Live option quote"),
        ("/v3/option/quotes", "Option quotes"),

        # Stream/real-time
        ("/v3/option/stream", "Stream endpoint"),
        ("/v3/option/subscribe", "Subscribe to stream"),

        # Already-known working endpoints
        ("/v3/option/list/symbols", "Symbol list (known working)"),
        ("/v3/option/list/expirations", "Expirations list (known working)"),
        ("/v3/option/history/eod", "End-of-day history (known working)"),
    ]

    results = []

    print("\n" + "="*70)
    print("TESTING THETADATA OPTION ENDPOINTS")
    print("="*70)
    print(f"Base URL: {BASE_URL}")
    print(f"Test symbol: {symbol}")
    print(f"Test expiration: {expiration}\n")

    for endpoint, description in endpoints:
        try:
            # Build request based on endpoint
            params = {"format": "json"}

            if "list" in endpoint:
                # Symbol list
                if "symbols" in endpoint:
                    pass  # No params needed
                # Expirations
                elif "expirations" in endpoint:
                    params["symbol"] = symbol
                # History endpoints need symbol and expiration
            elif "history" in endpoint:
                params["symbol"] = symbol
                params["expiration"] = expiration
                # Add date range for history requests
                today = datetime.now()
                start_dt = today - timedelta(days=1)
                end_dt = today
                params["start_date"] = start_dt.strftime("%Y%m%d")
                params["end_date"] = end_dt.strftime("%Y%m%d")
            elif "quote" in endpoint:
                params["symbol"] = symbol
                params["expiration"] = expiration
                params["strike"] = "400"
                params["right"] = "C"

            print(f"Testing: {endpoint}")
            print(f"  Description: {description}")
            print(f"  Params: {params}")

            response = requests.get(
                f"{BASE_URL}{endpoint}",
                params=params,
                timeout=TIMEOUT
            )

            status = response.status_code
            status_text = response.reason

            # Check if endpoint exists
            if status == 404:
                result = "NOT FOUND (endpoint doesn't exist)"
                color = "❌"
            elif status == 401:
                result = "UNAUTHORIZED (may need authentication)"
                color = "⚠️ "
            elif status == 403:
                result = "FORBIDDEN (subscription limitation)"
                color = "⚠️ "
            elif status == 200:
                # Got data
                try:
                    data = response.json()
                    # Check if response is empty
                    if isinstance(data, dict):
                        if data.get("response") == [] or len(data.get("response", [])) == 0:
                            result = "AVAILABLE but NO DATA for this request"
                            color = "⚠️ "
                        else:
                            result = "AVAILABLE with data ✓"
                            color = "✅"
                    else:
                        result = "AVAILABLE with data ✓"
                        color = "✅"
                except:
                    result = "AVAILABLE (response received)"
                    color = "✅"
            elif status == 400:
                result = f"BAD REQUEST (invalid params: {response.text[:50]})"
                color = "⚠️ "
            elif status == 429:
                result = "RATE LIMITED (too many requests)"
                color = "⚠️ "
            elif status == 500:
                result = f"SERVER ERROR ({status_text})"
                color = "❌"
            else:
                result = f"HTTP {status}: {status_text}"
                color = "⚠️ "

            print(f"  Result: {color} {result}")
            results.append({
                "endpoint": endpoint,
                "description": description,
                "status": status,
                "result": result
            })

        except requests.exceptions.Timeout:
            print(f"  Result: ⏱️  TIMEOUT (endpoint very slow)")
            results.append({
                "endpoint": endpoint,
                "description": description,
                "status": "TIMEOUT",
                "result": "TIMEOUT"
            })
        except Exception as e:
            print(f"  Result: ❌ ERROR - {str(e)[:50]}")
            results.append({
                "endpoint": endpoint,
                "description": description,
                "status": "ERROR",
                "result": str(e)
            })

        print()

    # Summary
    print("="*70)
    print("SUMMARY")
    print("="*70)

    working = [r for r in results if r["status"] == 200]
    minute_endpoints = [r for r in working if any(x in r["endpoint"] for x in ["minute", "tick", "intraday", "bars"])]

    print(f"\nTotal endpoints tested: {len(results)}")
    print(f"Working endpoints (HTTP 200): {len(working)}")
    print(f"Minute/intraday endpoints found: {len(minute_endpoints)}")

    if working:
        print("\n✅ Working endpoints:")
        for r in working:
            print(f"  - {r['endpoint']}: {r['description']}")

    if minute_endpoints:
        print("\n✅ MINUTE-LEVEL DATA IS AVAILABLE:")
        for r in minute_endpoints:
            print(f"  - {r['endpoint']}")
    else:
        print("\n❌ NO minute-level endpoints available in v3 API")
        print("   Available: END-OF-DAY (EOD) data only")

    return results


if __name__ == "__main__":
    test_endpoints()
