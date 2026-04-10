import os
import requests
import time
from dotenv import load_dotenv

load_dotenv("c:/Users/YS/Desktop/안티그래피티/주식투자하는에이전트(알파)/.env")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")

now_ts = int(time.time())
one_year_ago = now_ts - (365 * 24 * 60 * 60)
url = f"https://finnhub.io/api/v1/stock/candle?symbol=AAPL&resolution=D&from={one_year_ago}&to={now_ts}&token={FINNHUB_KEY}"
r = requests.get(url)
print("statusCode:", r.status_code)
print("response:", r.json())

earning_url = f"https://finnhub.io/api/v1/stock/earnings?symbol=AAPL&limit=8&token={FINNHUB_KEY}"
r2 = requests.get(earning_url)
print("earning status:", r2.status_code)
if r2.status_code == 200:
    print("earning response len:", len(r2.json()))
    print("earning:", r2.json()[:2] if isinstance(r2.json(), list) else r2.json())
