import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("FMP_API_KEY")
print(f"FMP Key: {key[:5]}...{key[-5:]}" if key else "NO KEY")

# Test Earnings Surprise for NVDA
r = requests.get(f"https://financialmodelingprep.com/api/v3/earnings-surprises/NVDA?apikey={key}", timeout=10)
print(f"Status: {r.status_code}")
data = r.json()
print(f"Data count: {len(data)}")
if data:
    surprise = data[0].get("percentageEarningsSurprise", "N/A")
    print(f"Latest surprise: {surprise}%")

# Test Financial Growth for NVDA
r2 = requests.get(f"https://financialmodelingprep.com/api/v3/financial-growth/NVDA?period=quarter&limit=1&apikey={key}", timeout=10)
print(f"Growth Status: {r2.status_code}")
g_data = r2.json()
if g_data:
    eps_growth = g_data[0].get("epsgrowth", "N/A")
    print(f"EPS Growth: {eps_growth}")
