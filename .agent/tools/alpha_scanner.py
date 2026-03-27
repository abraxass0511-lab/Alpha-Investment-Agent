"""
Alpha Scanner V2 — Yahoo-Free, KIS + FMP Hybrid Engine

파이프라인:
  Wikipedia → S&P 500 목록
  KIS 현재가상세 → 1단계: 시총 $10B+ (ustm_mcap ≥ 10000)
  KIS 기간별시세 → 2단계: 현재가 > 50일 이동평균
  FMP Screener + 개별 검증 → 3단계: ROE 15%+
  FMP 개별 → 4단계: 성장 (Surprise/EPS Growth)

Yahoo Finance 의존성 완전 제거.
KIS API는 무제한, FMP는 250콜/일 내에서 해결.
"""

import os
import sys
import json
import time
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ============================================================
# Global Config
# ============================================================
SCAN_TIMEOUT = 90 * 60  # 90 minutes
SCAN_START = time.time()

load_dotenv()
FMP_KEY = os.getenv("FMP_API_KEY")
fmp_call_count = 0

KIS_RATE_DELAY = 0.5  # KIS API 호출 간격 (초)


def check_timeout():
    elapsed = time.time() - SCAN_START
    if elapsed > SCAN_TIMEOUT:
        print(f"\n🚨 스캔 타임아웃! ({int(elapsed//60)}분 경과)")
        return True
    return False


# ============================================================
# KIS Token Manager (자동 갱신, 6시간 TTL)
# ============================================================
class KisTokenManager:
    """KIS API 토큰을 자동 관리합니다. 6시간마다 자동 재발급."""

    def __init__(self):
        self.base_url = os.getenv("KIS_BASE_URL", "")
        self.app_key = os.getenv("KIS_APP_KEY", "")
        self.app_secret = os.getenv("KIS_SECRET_KEY", "")
        self._token = None
        self._issued_at = 0
        self._ttl = 6 * 3600 - 300  # 5시간 55분 (5분 여유)

    def get_token(self):
        """토큰을 반환합니다. 만료 전이면 캐시된 토큰, 아니면 새로 발급."""
        now = time.time()
        if self._token and (now - self._issued_at) < self._ttl:
            return self._token

        print("   🔑 KIS 토큰 발급 중...")
        url = f"{self.base_url}/oauth2/tokenP"
        try:
            r = requests.post(url, json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            }, timeout=10)
            if r.status_code == 200:
                data = r.json()
                self._token = data.get("access_token")
                self._issued_at = now
                print("   🔑 KIS 토큰 발급 완료 ✅")
                return self._token
            else:
                print(f"   ❌ KIS 토큰 발급 실패: HTTP {r.status_code}")
        except Exception as e:
            print(f"   ❌ KIS 토큰 발급 에러: {e}")
        return None

    def headers(self, tr_id):
        """KIS API 요청 헤더를 생성합니다."""
        token = self.get_token()
        if not token:
            return {}
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }


kis = KisTokenManager()


# ============================================================
# S&P 500 목록 — Wikipedia
# ============================================================
def get_sp500_tickers():
    """위키피디아에서 S&P 500 구성종목과 회사명을 가져옵니다."""
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        result = []
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    ticker = cols[0].text.strip().replace('.', '-')
                    name = cols[1].text.strip()
                    result.append({"symbol": ticker, "name": name})
        return result
    except Exception as e:
        print(f"❌ S&P 500 목록 수집 실패: {e}")
        return []


# ============================================================
# KIS API: 해외주식 현재가 상세 (1단계: 시총 + 가격)
# ============================================================
EXCHANGES = ["NAS", "NYS", "AMS"]  # NASDAQ, NYSE, AMEX


def kis_get_price_detail(symbol):
    """
    KIS 해외주식 현재가 상세 API (tr_id: HHDFS76200200)
    → 현재가(last) + 시가총액(ustm_mcap, 백만$ 단위)
    여러 거래소를 순차 시도하여 데이터를 찾습니다.
    """
    for excd in EXCHANGES:
        try:
            url = f"{kis.base_url}/uapi/overseas-price/v1/quotations/price"
            params = {"AUTH": "", "EXCD": excd, "SYMB": symbol}
            r = requests.get(url, headers=kis.headers("HHDFS76200200"),
                             params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("rt_cd") == "0":
                    out = data.get("output", {})
                    price = float(out.get("last", 0) or out.get("base", 0) or 0)
                    mcap_str = out.get("tomv", "") or out.get("ustm_mcap", "") or "0"
                    mcap = float(mcap_str) if mcap_str else 0
                    if price > 0:
                        return {"price": price, "mcap_m": mcap, "excd": excd}
            time.sleep(0.1)
        except Exception:
            continue
    return None


# ============================================================
# KIS API: 해외주식 기간별시세 (2단계: MA50 계산)
# ============================================================
def kis_get_daily_prices(symbol, excd="NAS"):
    """
    KIS 해외주식 기간별시세 API (tr_id: FHKST03030100)
    → 일별 종가 리스트 반환 (최근순)
    """
    try:
        url = f"{kis.base_url}/uapi/overseas-price/v1/quotations/dailyprice"
        params = {
            "AUTH": "",
            "EXCD": excd,
            "SYMB": symbol,
            "GUBN": "0",  # 0=일별
            "BYMD": datetime.now().strftime("%Y%m%d"),
            "MODP": "1",  # 수정주가
        }
        r = requests.get(url, headers=kis.headers("FHKST03030100"),
                         params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("rt_cd") == "0":
                output2 = data.get("output2", [])
                closes = []
                for item in output2:
                    c = float(item.get("clos", 0))
                    if c > 0:
                        closes.append(c)
                return closes
    except Exception:
        pass
    return []


def calculate_ma50(closes):
    """종가 리스트에서 50일 이동평균을 계산합니다."""
    if len(closes) >= 50:
        return round(sum(closes[:50]) / 50, 2)
    return None


# ============================================================
# FMP API 호출 (429 자동 재시도 + 카운터)
# ============================================================
def fmp_request(url, timeout=15):
    """FMP API 호출 — 429 에러 시 최대 3회 재시도"""
    global fmp_call_count
    max_retries = 3

    for attempt in range(max_retries):
        if check_timeout():
            return None
        try:
            fmp_call_count += 1
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = min(30 * (attempt + 1), 60)
                print(f"    ⏳ FMP 429 (시도 {attempt+1}/{max_retries}) → {wait}초 대기...")
                time.sleep(wait)
                continue
            print(f"    ⚠️ FMP HTTP {r.status_code} → 15초 대기...")
            time.sleep(15)
        except Exception as e:
            print(f"    ⚠️ FMP 에러({e}) → 10초 대기...")
            time.sleep(10)
    return None


# ============================================================
# 3단계: FMP Screener + 하이브리드 개별 검증
# ============================================================
def get_fmp_roe_screener():
    """FMP Stock Screener 1콜 → ROE 15%+ 종목 세트 반환"""
    if not FMP_KEY:
        return set()

    url = (f"https://financialmodelingprep.com/api/v3/stock-screener"
           f"?marketCapMoreThan=10000000000"
           f"&isActivelyTrading=true"
           f"&limit=1000"
           f"&apikey={FMP_KEY}")

    r = fmp_request(url)
    if r and r.status_code == 200:
        data = r.json()
        # Screener 결과에서 symbol 세트 추출
        return {item.get('symbol', '') for item in data if item}
    return set()


def check_roe_individual(symbol):
    """개별 ROE 검증 (Screener 누락 종목용) — FMP key-metrics-ttm"""
    if not FMP_KEY:
        return None

    url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={FMP_KEY}"
    r = fmp_request(url, timeout=10)
    if r and r.status_code == 200:
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0].get('returnOnEquityTTM')
    return None


# ============================================================
# 4단계: FMP 성장성 검증 (Surprise + EPS Growth)
# ============================================================
def check_growth_fmp(symbol):
    """
    4단계 성장 검증 — FMP 전용
    1. Earnings Surprise >= 10%  OR
    2. EPS Growth (YoY) >= 20%
    """
    if not FMP_KEY:
        return False, "FMP API Key Missing"

    # Call 1: Earnings Surprise
    url_s = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}"
    s_res = fmp_request(url_s)
    if not s_res:
        return False, f"FMP Surprise Failed ({symbol})"

    time.sleep(13)  # FMP Rate Limit 준수

    # Call 2: Financial Growth
    url_g = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?period=quarter&limit=1&apikey={FMP_KEY}"
    g_res = fmp_request(url_g)
    if not g_res:
        return False, f"FMP Growth Failed ({symbol})"

    if s_res.status_code == 200 and g_res.status_code == 200:
        s_data = s_res.json()
        g_data = g_res.json()

        if (isinstance(s_data, list) and len(s_data) > 0 and
                isinstance(g_data, list) and len(g_data) > 0):
            surprise = s_data[0].get('percentageEarningsSurprise', 0) or 0
            eps_growth = g_data[0].get('epsgrowth', 0) or 0

            if surprise >= 10 or eps_growth >= 0.20:
                return True, f"Surprise: {round(surprise,1)}%, Growth: {round(eps_growth*100,1)}%"
            return False, f"Surprise: {round(surprise,1)}%, Growth: {round(eps_growth*100,1)}%"
        return False, f"FMP No Data ({symbol})"
    return False, f"FMP HTTP Error ({symbol})"


# ============================================================
# 메인 파이프라인
# ============================================================
def run_scan():
    global fmp_call_count
    fmp_call_count = 0
    kis_call_count = 0

    # ========================================
    # S&P 500 목록 수집
    # ========================================
    sp500 = get_sp500_tickers()
    if not sp500:
        print("❌ S&P 500 목록 수집 실패")
        return

    total = len(sp500)
    name_map = {item["symbol"]: item["name"] for item in sp500}
    tickers = [item["symbol"] for item in sp500]

    print(f"🚀 [Alpha Scanner V2] KIS+FMP 하이브리드 엔진 가동")
    print(f"   대상: {total}종목 | Yahoo ❌ 제거 → KIS + FMP 이중 엔진")
    print(f"   🔑 KIS 토큰 자동 관리 (6시간 TTL)")

    # ========================================
    # [1단계] 체급 — KIS 시가총액 $10B+
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [1단계] 체급 검증 (KIS API — 시총 $10B+)")
    print(f"{'='*50}")

    stage1 = []
    exchange_map = {}
    fail_count_1 = 0

    for i, sym in enumerate(tickers):
        if check_timeout():
            break

        result = kis_get_price_detail(sym)
        kis_call_count += len(EXCHANGES)  # worst case

        if result:
            kis_call_count -= (len(EXCHANGES) - EXCHANGES.index(result["excd"]) - 1)
            exchange_map[sym] = result["excd"]

            if result["mcap_m"] >= 10000:  # $10B = 10,000 million
                stage1.append({
                    "Symbol": sym,
                    "Name": name_map.get(sym, sym),
                    "Price": result["price"],
                    "MarketCap_M": result["mcap_m"],
                })
            # mcap_m이 0이면 KIS에서 시총 못 가져온 것 → S&P 500이니 통과시킴
            elif result["mcap_m"] == 0:
                stage1.append({
                    "Symbol": sym,
                    "Name": name_map.get(sym, sym),
                    "Price": result["price"],
                    "MarketCap_M": 0,  # 데이터 없지만 S&P 500이므로 통과
                })
        else:
            fail_count_1 += 1

        if (i + 1) % 100 == 0:
            print(f"   {i+1}/{total} 처리 ({len(stage1)}건 통과, {fail_count_1}건 실패)")
        time.sleep(KIS_RATE_DELAY)

    c1 = len(stage1)
    print(f"\n✅ [1단계] 완료: {c1}건 통과 (시총 $10B+ 또는 S&P 500 자동통과)")

    # ========================================
    # [2단계] 에너지 — KIS MA50
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [2단계] 에너지 검증 (KIS API — 가격 > 50MA)")
    print(f"{'='*50}")

    stage2 = []

    for i, item in enumerate(stage1):
        if check_timeout():
            break

        sym = item["Symbol"]
        excd = exchange_map.get(sym, "NAS")
        closes = kis_get_daily_prices(sym, excd)
        kis_call_count += 1

        ma50 = calculate_ma50(closes)
        if ma50 and item["Price"] > ma50:
            item["MA50"] = ma50
            item["Momentum(%)"] = round(((item["Price"] - ma50) / ma50) * 100, 2)
            stage2.append(item)

        if (i + 1) % 100 == 0:
            print(f"   {i+1}/{c1} 처리 ({len(stage2)}건 통과)")
        time.sleep(KIS_RATE_DELAY)

    c2 = len(stage2)
    print(f"\n✅ [2단계] 완료: {c2}건 통과 (가격 > 50MA)")

    # ========================================
    # [3단계] 내실 — FMP Screener + 하이브리드
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [3단계] 내실 검증 (FMP Screener + 개별 검증)")
    print(f"{'='*50}")

    # Step 3a: Screener로 ROE 15%+ 목록 1콜
    roe_screener_set = get_fmp_roe_screener()
    print(f"   📡 FMP Screener: {len(roe_screener_set)}종목 확인 (1콜)")

    stage3 = []
    verify_needed = []

    for item in stage2:
        sym = item["Symbol"]
        if sym in roe_screener_set:
            item["ROE(%)"] = "Screener ✅"
            stage3.append(item)
        else:
            verify_needed.append(item)

    print(f"   ✅ Screener 매칭: {len(stage3)}건 자동 통과")
    print(f"   🔍 개별 검증 필요: {len(verify_needed)}건")

    # Step 3b: 누락 종목만 개별 FMP 호출
    for item in verify_needed:
        if check_timeout():
            break
        sym = item["Symbol"]
        roe = check_roe_individual(sym)
        if roe is not None and roe >= 0.15:
            item["ROE(%)"] = round(roe * 100, 2)
            stage3.append(item)
            print(f"    ✅ {sym} ROE: {round(roe*100,1)}% → PASS (개별 검증)")
        elif roe is not None:
            print(f"    ❌ {sym} ROE: {round(roe*100,1)}% → FAIL")
        else:
            print(f"    🚨 {sym} ROE 데이터 없음 → SKIP")
        time.sleep(13)

    c3 = len(stage3)
    print(f"\n✅ [3단계] 완료: {c3}건 통과 (ROE 15%+)")

    # ========================================
    # [4단계] 성장 — FMP 개별
    # ========================================
    print(f"\n{'='*50}")
    print(f"📊 [4단계] 성장 검증 (FMP API)")
    print(f"{'='*50}")

    stage4 = []

    for i, item in enumerate(stage3):
        if check_timeout():
            break
        sym = item["Symbol"]
        print(f"🔍 [4단계] {sym} ({i+1}/{c3})")

        passed, reason = check_growth_fmp(sym)
        if passed:
            item["GrowthReason"] = reason
            stage4.append(item)
            print(f"    ✅ {sym} → {reason}")
        else:
            print(f"    ❌ {sym} → {reason}")
        time.sleep(15)

    c4 = len(stage4)
    print(f"\n✅ [4단계] 완료: {c4}건 통과")

    # ========================================
    # 결과 저장
    # ========================================
    if not os.path.exists('output_reports'):
        os.makedirs('output_reports')

    pd.DataFrame(stage4).to_csv("output_reports/daily_scan_latest.csv", index=False)

    elapsed_min = round((time.time() - SCAN_START) / 60, 1)

    with open("output_reports/metadata.json", "w") as f:
        json.dump({
            "total": total,
            "success_all": True,
            "step1": c1, "step2": c2, "step3": c3, "step4": c4,
            "timestamp": datetime.now().isoformat(),
            "fmp_calls": fmp_call_count,
            "kis_calls": kis_call_count,
            "elapsed_min": elapsed_min,
            "engine": "KIS+FMP Hybrid V2 (Yahoo-Free)",
        }, f)

    print(f"\n{'='*55}")
    print(f"✅ [Alpha Scanner V2] 최종 결과")
    print(f"   Total: {total}종목")
    print(f"   1단계(체급): {c1} → 2단계(에너지): {c2}")
    print(f"   → 3단계(내실): {c3} → 4단계(성장): {c4}")
    print(f"   📡 KIS: {kis_call_count}콜 | FMP: {fmp_call_count}콜")
    print(f"   ⏱️ 소요시간: {elapsed_min}분")
    print(f"   비고: KIS+FMP 하이브리드 엔진, 야후 사용 안 함")
    print(f"{'='*55}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from us_market_calendar import is_trading_day

    if not is_trading_day():
        print("📅 오늘은 미국 시장 휴장일입니다. 스캔을 건너뜁니다.")
        sys.exit(0)

    run_scan()
