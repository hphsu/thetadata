"""
Test direct ThetaData HTTP API access (not the local daemon)
Requires API key in environment or config
"""
import requests
import os
from datetime import datetime, timedelta

def test_direct_api():
    """Test ThetaData direct API endpoints"""

    # Check for API key
    api_key = os.environ.get('THETADATA_API_KEY')

    if not api_key:
        print("\n" + "="*70)
        print("DIRECT THETADATA API TEST")
        print("="*70)
        print("\n⚠️  No API key found in environment variable THETADATA_API_KEY")
        print("\nTo use ThetaData direct API (with minute-level data):")
        print("1. Export your API key: export THETADATA_API_KEY='your_key_here'")
        print("2. Or add to config file")
        print("\nDirect API endpoints (vs local daemon):")
        print("  Local daemon (port 25503):  /v3/option/history/eod only")
        print("  Direct API:  /option/history/minute, /quotes, /last, etc.")
        print("\nTo get your API key:")
        print("  1. Log in to ThetaData.com")
        print("  2. Go to Account → API Keys")
        print("  3. Copy your API key")
        return

    print("\n" + "="*70)
    print("DIRECT THETADATA API TEST")
    print("="*70)
    print(f"API Key found: {api_key[:10]}..." if api_key else "No API key")

    base_url = "https://api.thetadata.us"
    headers = {"Authorization": f"Bearer {api_key}"}

    # Test endpoints
    symbol = "SPY"
    expiration = "20260131"
    strike = "400"
    right = "C"

    endpoints = [
        (f"/option/quote?root={symbol}&expiration={expiration}&strike={strike}&right={right}",
         "Live option quote"),
        (f"/option/history/minute?root={symbol}&expiration={expiration}&start_date=20250126&end_date=20250127",
         "Minute-level history"),
        (f"/option/expirations?root={symbol}",
         "Option expirations"),
    ]

    print(f"\nTesting direct API endpoints...\n")

    for endpoint, description in endpoints:
        try:
            print(f"Testing: {endpoint}")
            print(f"  Description: {description}")

            response = requests.get(
                f"{base_url}{endpoint}",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data and len(str(data)) > 20:
                    print(f"  Result: ✅ AVAILABLE with data")
                else:
                    print(f"  Result: ⚠️  Available but no data: {data}")
            elif response.status_code == 401:
                print(f"  Result: ❌ Unauthorized (invalid API key)")
            elif response.status_code == 404:
                print(f"  Result: ❌ Not found (endpoint doesn't exist)")
            else:
                print(f"  Result: ⚠️  HTTP {response.status_code}: {response.text[:100]}")

        except Exception as e:
            print(f"  Result: ❌ Error: {str(e)[:50]}")

        print()


if __name__ == "__main__":
    test_direct_api()
