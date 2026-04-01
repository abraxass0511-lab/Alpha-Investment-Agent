import os
import json
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

class AlphaTrader:
    """에이전트 알파의 칼날 — KIS 모의투자 해외주식 자동매매 모듈 (공식 API 규격 준수)"""

    def __init__(self):
        # 깃허브 시크릿(금고)에서 정보 가져오기
        self.app_key = os.getenv("KIS_APP_KEY")
        self.secret_key = os.getenv("KIS_SECRET_KEY")
        self.cano = os.getenv("KIS_CANO")                  # 계좌번호 앞 8자리
        self.acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD")  # 계좌상품코드 뒤 2자리
        self.base_url = os.getenv("KIS_BASE_URL")           # https://openapivts.koreainvestment.com:29443

        self.access_token = None
        self.token_expiry = None

    # ───────────────────────────────────────────────────────────
    # 1. 인증 (OAuth Token)
    # ───────────────────────────────────────────────────────────
    def get_access_token(self):
        """24시간짜리 Access Token을 발급받습니다. Rate Limit 시 자동 재시도."""
        if self.access_token and self.token_expiry and self.token_expiry > datetime.now():
            return self.access_token

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.secret_key
        }

        for attempt in range(3):
            try:
                res = requests.post(url, json=payload)
                data = res.json()
                if "access_token" in data:
                    self.access_token = data["access_token"]
                    self.token_expiry = datetime.now() + timedelta(hours=23)
                    print("✅ KIS 토큰 발급 성공!")
                    return self.access_token
                else:
                    err = data.get('error_description', str(data))
                    print(f"⚠️ 토큰 발급 실패 ({attempt+1}/3): {err}")
                    if '1분당' in err or 'EGW' in data.get('error_code', ''):
                        print("⏳ Rate Limit — 65초 대기 후 재시도...")
                        time.sleep(65)
                    else:
                        return None
            except Exception as e:
                print(f"🚨 KIS 연결 에러: {e}")
                return None
        return None

    def _make_headers(self, tr_id):
        """공통 헤더를 생성합니다."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": tr_id
        }

    # ───────────────────────────────────────────────────────────
    # 2. 예수금 조회 (체결기준 현재잔고) [v1_해외주식-008]
    #    → 통화별 예수금 (USD, JPY, HKD 등) + 원화 합산
    #    → 앱의 "예수금" 버튼과 동일
    # ───────────────────────────────────────────────────────────
    def get_deposit(self):
        """통화별 예수금(총 매수가능금액)을 조회합니다."""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"

        # 공식 tr_id: 모의투자 VTRP6504R / 실전 CTRP6504R
        headers = self._make_headers("VTRP6504R")
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "WCRC_FRCR_DVSN_CD": "01",  # 원화(01)
            "NATN_CD": "840",            # 미국(840)
            "TR_MKET_CD": "00",          # 전체시장
            "INQR_DVSN_CD": "00"         # 전체조회
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                return {
                    "output2": data.get('output2', []),  # 통화별 예수금 내역
                    "output3": data.get('output3', {}),  # 합산 총계
                }
            else:
                print(f"❌ 예수금 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 예수금 조회 에러: {e}")
            return None

    # ───────────────────────────────────────────────────────────
    # 3. 해외주식 매수가능금액 조회 [v1_해외주식-014]
    #    → 특정 종목의 매수가능수량/금액
    # ───────────────────────────────────────────────────────────
    def get_buying_power(self, symbol="AAPL", price="0"):
        """해외주식 매수가능금액을 조회합니다."""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-psamount"

        # 공식 tr_id: 모의투자 VTTS3007R / 실전 TTTS3007R
        headers = self._make_headers("VTTS3007R")
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "OVRS_ORD_UNPR": price,
            "ITEM_CD": symbol,
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                output = data.get('output', {})
                return {
                    "ord_psbl_frcr_amt": output.get("ovrs_ord_psbl_amt", "0"),
                    "max_ord_psbl_qty": output.get("max_ord_psbl_qty", "0"),
                }
            else:
                print(f"❌ 매수가능금액 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 매수가능금액 조회 에러: {e}")
            return None

    # ───────────────────────────────────────────────────────────
    # 4. 해외주식 잔고 조회 [v1_해외주식-006]
    #    → 보유 종목 목록 + 평가손익
    # ───────────────────────────────────────────────────────────
    def get_balance(self):
        """보유 종목과 평가손익을 조회합니다. (NASD+NYSE+AMEX 전체)"""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = self._make_headers("VTTS3012R")

        all_holdings = []
        bal_summary = {}

        for excg in ["NASD", "NYSE", "AMEX"]:
            params = {
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": excg,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }

            try:
                res = requests.get(url, headers=headers, params=params)
                data = res.json()
                if data.get('rt_cd') == '0':
                    all_holdings.extend(data.get('output1', []))
                    if not bal_summary:
                        bal_summary = data.get('output2', {})
                else:
                    print(f"⚠️ {excg} 잔고 조회 실패: {data.get('msg1')}")
            except Exception as e:
                print(f"⚠️ {excg} 잔고 조회 에러: {e}")

        if not all_holdings and not bal_summary:
            return None

        # 중복 제거 (같은 종목이 여러 거래소에서 반환될 경우)
        seen = set()
        unique_holdings = []
        for h in all_holdings:
            sym = h.get('ovrs_pdno', '')
            if sym and sym not in seen:
                seen.add(sym)
                unique_holdings.append(h)

        return unique_holdings, bal_summary

    # ───────────────────────────────────────────────────────────
    # 5. 해외주식 매수 주문 [v1_해외주식-001]
    # ───────────────────────────────────────────────────────────
    def buy_order(self, symbol, quantity, price, exchange="NASD"):
        """해외주식 지정가 매수 주문을 실행합니다."""
        token = self.get_access_token()
        if not token:
            return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"

        # 공식 tr_id: 모의투자 미국 매수 VTTT1002U / 실전 TTTT1002U
        headers = self._make_headers("VTTT1002U")
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

        try:
            res = requests.post(url, headers=headers, json=payload)
            data = res.json()
            if data.get('rt_cd') == '0':
                odno = data.get('output', {}).get('ODNO', 'N/A')
                print(f"🎯 [매수 성공] {symbol} {quantity}주 @ ${price} (주문번호: {odno})")
                return True
            else:
                print(f"❌ [매수 실패] {data.get('msg1')}")
                return False
        except Exception as e:
            print(f"🚨 매수 에러: {e}")
            return False

    # ───────────────────────────────────────────────────────────
    # 6. 해외주식 매도 주문 [v1_해외주식-001]
    # ───────────────────────────────────────────────────────────
    def sell_order(self, symbol, quantity, price, exchange="NASD"):
        """해외주식 지정가 매도 주문을 실행합니다."""
        token = self.get_access_token()
        if not token:
            return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"

        # 공식 tr_id: 모의투자 미국 매도 VTTT1006U / 실전 TTTT1006U
        headers = self._make_headers("VTTT1006U")
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

        try:
            res = requests.post(url, headers=headers, json=payload)
            data = res.json()
            if data.get('rt_cd') == '0':
                odno = data.get('output', {}).get('ODNO', 'N/A')
                print(f"🔻 [매도 성공] {symbol} {quantity}주 @ ${price} (주문번호: {odno})")
                return True
            else:
                print(f"❌ [매도 실패] {data.get('msg1')}")
                return False
        except Exception as e:
            print(f"🚨 매도 에러: {e}")
            return False

    # ───────────────────────────────────────────────────────────
    # 7. 주문 체결내역 조회 [v1_해외주식-007]
    #    → 오늘 주문한 내역의 체결/미체결 확인
    # ───────────────────────────────────────────────────────────
    def get_order_status(self):
        """오늘의 주문 체결내역을 조회합니다."""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-ccnl"

        # 공식 tr_id: 모의투자 VTTS3035R / 실전 TTTS3035R
        headers = self._make_headers("VTTS3035R")
        today = datetime.now().strftime("%Y%m%d")

        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": "",              # 전체 종목 (모의투자는 ""만 가능)
            "ORD_STRT_DT": today,
            "ORD_END_DT": today,
            "SLL_BUY_DVSN": "00",    # 전체 (모의투자는 "00"만 가능)
            "CCLD_NCCS_DVSN": "00",  # 전체 (모의투자는 "00"만 가능)
            "OVRS_EXCG_CD": "",      # 전체 (모의투자는 ""만 가능)
            "SORT_SQN": "DS",
            "ORD_DT": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_NK200": "",
            "CTX_AREA_FK200": "",
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                orders = data.get('output', [])
                return orders
            else:
                print(f"❌ 체결내역 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 체결내역 조회 에러: {e}")
            return None

    # ───────────────────────────────────────────────────────────
    # 8. 해외주식 현재가 조회 [v1_해외주식-010]
    #    → 가디언이 -10% 하락 판단시 사용
    # ───────────────────────────────────────────────────────────
    def get_current_price(self, symbol, exchange="NAS"):
        """해외주식 현재가를 조회합니다."""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"

        # 공식 tr_id: 모의/실전 동일 HHDFS00000300
        headers = self._make_headers("HHDFS00000300")
        params = {
            "AUTH": "",
            "EXCD": exchange,    # NAS(나스닥), NYS(뉴욕), AMS(아멕스)
            "SYMB": symbol,
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                output = data.get('output', {})
                return {
                    "price": float(output.get("last", "0")),      # 현재가
                    "diff": output.get("diff", "0"),               # 전일대비
                    "rate": output.get("rate", "0"),                # 등락률
                    "high": output.get("high", "0"),               # 고가
                    "low": output.get("low", "0"),                 # 저가
                }
            else:
                print(f"❌ 현재가 조회 실패 ({symbol}): {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 현재가 조회 에러: {e}")
            return None


# ═══════════════════════════════════════════════════════════════
# 메인: 종합 연결 테스트
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    trader = AlphaTrader()
    print("=" * 55)
    print("🏦 KIS 모의투자 계좌 종합 점검")
    print("=" * 55)

    # ─── 1. 예수금 (통화별 총 매수가능금액) ───
    print("\n💰 [예수금] (통화별 총 매수가능금액)")
    print("-" * 45)
    deposit = trader.get_deposit()
    if deposit:
        currencies = deposit.get("output2", [])
        summary = deposit.get("output3", {})

        if currencies:
            total_krw = 0
            for cur in currencies:
                crcy = cur.get('crcy_cd', '?')
                deposit_amt = cur.get('frcr_dncl_amt_2', '0')
                evlu_amt_krw = cur.get('evlu_amt_smtl_amt', '0')
                if float(deposit_amt) > 0:
                    print(f"  🏷️ {crcy}: {deposit_amt} (원화환산: ₩{evlu_amt_krw})")
                    try:
                        total_krw += float(evlu_amt_krw)
                    except:
                        pass
            if total_krw > 0:
                print(f"  ────────────────────────────────")
                print(f"  💎 총 예수금 (원화환산): ₩{total_krw:,.0f}")
        else:
            print("  📭 통화별 예수금 데이터 없음")

        # output3 합산 정보
        if summary:
            tot_asst = summary.get('tot_asst_amt', 'N/A')
            tot_evlu = summary.get('tot_evlu_pfls_amt', 'N/A')
            print(f"\n  📊 총 자산평가액: ₩{tot_asst}")
            print(f"  📊 총 평가손익: ₩{tot_evlu}")
    else:
        print("  ❌ 예수금 조회 실패")

    # ─── 2. USD 매수가능금액 ───
    print(f"\n💵 [USD 매수가능금액]")
    print("-" * 45)
    power = trader.get_buying_power(symbol="AAPL", price="252.62")
    if power:
        print(f"  💰 USD 주문가능금액: ${power['ord_psbl_frcr_amt']}")
        print(f"  📊 AAPL 최대 매수가능: {power['max_ord_psbl_qty']}주")
    else:
        print("  ❌ 매수가능금액 조회 실패")

    # ─── 3. 보유 종목 ───
    print(f"\n📊 [보유 종목]")
    print("-" * 45)
    result = trader.get_balance()
    if result:
        holdings, bal_summary = result
        if holdings:
            for h in holdings:
                sym = h.get('ovrs_pdno', '?')
                qty = h.get('ovrs_cblc_qty', '0')
                buy_avg = h.get('pchs_avg_pric', '0')
                cur = h.get('now_pric2', '0')
                pnl = h.get('frcr_evlu_pfls_amt', '0')
                pnl_rate = h.get('evlu_pfls_rt', '0')
                print(f"  📈 {sym}: {qty}주 | 매입: ${buy_avg} | 현재: ${cur} | 손익: ${pnl} ({pnl_rate}%)")
        else:
            print("  📭 보유 종목 없음")

    print("\n" + "=" * 55)
    print("🏁 점검 완료!")
