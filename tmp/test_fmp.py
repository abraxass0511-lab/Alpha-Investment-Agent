import os
import requests
from dotenv import load_dotenv

load_dotenv()
FMP_KEY = os.getenv("FMP_API_KEY")

def test_fmp_growth(ticker):
    print(f"--- Testing {ticker} ---")
    # 1. Earnings Surprise
    url_surprise = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{ticker}?apikey={FMP_KEY}"
    r_s = requests.get(url_surprise)
    print(f"Surprise Status: {r_s.status_code}")
    if r_s.status_code == 200:
        data = r_s.json()
        if data:
            print(f"Last Surprise: {data[0].get('symbol')} - {data[0].get('percentageEarningsSurprise')}%")
        else:
            print("No surprise data found.")
    
    # 2. Financial Growth
    url_growth = f"https://financialmodelingprep.com/api/v3/financial-growth/{ticker}?period=quarter&limit=1&apikey={FMP_KEY}"
    r_g = requests.get(url_growth)
    print(f"Growth Status: {r_g.status_code}")
    if r_g.status_code == 200:
        data = r_g.json()
        if data:
            print(f"Last EPS Growth: {data[0].get('symbol')} - {data[0].get('epsgrowth')}")
        else:
            print("No growth data found.")

if __name__ == "__main__":
    test_fmp_growth("AAPL")
    test_fmp_growth("NVDA")
