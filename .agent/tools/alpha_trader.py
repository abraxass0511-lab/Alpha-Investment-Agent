import os
import json
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# KIS 거래소 코드 매핑 (종목 → 거래소)
# ═══════════════════════════════════════════════════════════════
EXCHANGE_MAP = {
    "NASD": "NASD",  # 나스닥
    "NYSE": "NYSE",  # 뉴욕
    "AMEX": "AMEX",  # 아멕스
}

class AlphaTrader:
    """에이전트 알파의 칼날 — KIS 모의투자 해외주식 자동매매 모듈 (공식 API 규격 준수)"""

    def __init__(self):
        # 깃허브 시크릿(금고)에서 정보 가져오기
        self.app_key = os.getenv("KIS_APP_KEY")
        self.secret_key = os.getenv("KIS_SECRET_KEY")
        self.account_no = os.getenv("KIS_ACCOUNT_NO")
        self.base_url = os.getenv("KIS_BASE_URL")  # https://openapivts.koreainvestment.com:29443

        self.access_token = None
        self.token_expiry = None

    # ───────────────────────────────────────────────────────────
    # 1. 인증 (OAuth Token)
    # ───────────────────────────────────────────────────────────
    def get_access_token(self):
        """24시간짜리 Access Token을 발급받습니다."""
        if self.access_token and self.token_expiry and self.token_expiry > datetime.now():
            return self.access_token

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.secret_key
        }

        try:
            res = requests.post(url, json=payload)
            data = res.json()
            if "access_token" in data:
                self.access_token = data["access_token"]
                self.token_expiry = datetime.now() + timedelta(hours=23)
                print("✅ KIS 토큰 발급 성공!")
                return self.access_token
            else:
                print(f"❌ 토큰 발급 실패: {data}")
                return None
        except Exception as e:
            print(f"🚨 KIS 연결 에러: {e}")
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

    def _account_parts(self):
        """계좌번호를 앞8자리/뒤2자리로 분리합니다."""
        return self.account_no[:8], self.account_no[-2:]

    # ───────────────────────────────────────────────────────────
    # 2. 매수가능금액 조회 [v1_해외주식-014]
    #    → 앱의 "주문가능금액"과 동일한 값을 반환
    # ───────────────────────────────────────────────────────────
    def get_buying_power(self, symbol="AAPL", price="0"):
        """해외주식 매수가능금액을 조회합니다. (앱과 동일한 금액)"""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-psamount"
        acc_prefix, acc_suffix = self._account_parts()

        # 공식 tr_id: 모의투자 VTTS3007R / 실전 TTTS3007R
        headers = self._make_headers("VTTS3007R")
        params = {
            "CANO": acc_prefix,
            "ACNT_PRDT_CD": acc_suffix,
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
                    "ord_psbl_frcr_amt": output.get("ovrs_ord_psbl_amt", "0"),  # 외화주문가능금액
                    "max_ord_psbl_qty": output.get("max_ord_psbl_qty", "0"),     # 최대주문가능수량
                    "frcr_ord_psbl_amt1": output.get("frcr_ord_psbl_amt1", "0"), # 외화주문가능금액1
                }
            else:
                print(f"❌ 매수가능금액 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 매수가능금액 조회 에러: {e}")
            return None

    # ───────────────────────────────────────────────────────────
    # 3. 해외주식 잔고 조회 [v1_해외주식-006]
    #    → 보유 종목 목록 + 평가손익
    # ───────────────────────────────────────────────────────────
    def get_balance(self):
        """보유 종목과 평가손익을 조회합니다."""
        token = self.get_access_token()
        if not token:
            return None

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
        acc_prefix, acc_suffix = self._account_parts()

        # 공식 tr_id: 모의투자 VTTS3012R / 실전 TTTS3012R
        headers = self._make_headers("VTTS3012R")
        params = {
            "CANO": acc_prefix,
            "ACNT_PRDT_CD": acc_suffix,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                return data.get('output1', []), data.get('output2', {})
            else:
                print(f"❌ 잔고 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 잔고 조회 에러: {e}")
            return None

    # ───────────────────────────────────────────────────────────
    # 4. 해외주식 매수 주문 [v1_해외주식-001]
    # ───────────────────────────────────────────────────────────
    def buy_order(self, symbol, quantity, price, exchange="NASD"):
        """해외주식 지정가 매수 주문을 실행합니다."""
        token = self.get_access_token()
        if not token:
            return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        acc_prefix, acc_suffix = self._account_parts()

        # 공식 tr_id: 모의투자 미국 매수 VTTT1002U / 실전 TTTT1002U
        headers = self._make_headers("VTTT1002U")
        payload = {
            "CANO": acc_prefix,
            "ACNT_PRDT_CD": acc_suffix,
            "OVRS_EXCG_CD": exchange,       # NASD, NYSE, AMEX
            "PDNO": symbol,                  # 종목코드 (AAPL, MSFT 등)
            "ORD_QTY": str(quantity),         # 주문수량
            "OVRS_ORD_UNPR": str(price),      # 주문단가 (지정가)
            "CTAC_TLNO": "",                  # 연락전화번호(선택)
            "MGCO_APTM_ODNO": "",             # 운용사지정주문번호(선택)
            "ORD_SVR_DVSN_CD": "0",           # 주문서버구분코드
            "ORD_DVSN": "00"                  # 주문구분: 00=지정가 (모의투자는 지정가만 가능)
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
    # 5. 해외주식 매도 주문 [v1_해외주식-001]
    # ───────────────────────────────────────────────────────────
    def sell_order(self, symbol, quantity, price, exchange="NASD"):
        """해외주식 지정가 매도 주문을 실행합니다."""
        token = self.get_access_token()
        if not token:
            return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        acc_prefix, acc_suffix = self._account_parts()

        # 공식 tr_id: 모의투자 미국 매도 VTTT1006U / 실전 TTTT1006U
        headers = self._make_headers("VTTT1006U")
        payload = {
            "CANO": acc_prefix,
            "ACNT_PRDT_CD": acc_suffix,
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


# ═══════════════════════════════════════════════════════════════
# 메인: 종합 연결 테스트
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    trader = AlphaTrader()
    print("=" * 55)
    print("🏦 KIS 모의투자 계좌 종합 점검")
    print("=" * 55)

    # --- 매수가능금액 (앱과 동일 금액) ---
    print("\n💵 [매수가능금액] (앱 '주문가능금액'과 동일)")
    print("-" * 45)
    power = trader.get_buying_power(symbol="AAPL", price="252.62")
    if power:
        amt = power['ord_psbl_frcr_amt']
        qty = power['max_ord_psbl_qty']
        print(f"  💰 주문가능금액: ${amt}")
        print(f"  📊 AAPL 최대 매수가능수량: {qty}주")
    else:
        print("  ❌ 매수가능금액 조회 실패")

    # --- 보유 종목 ---
    print(f"\n📊 [보유 종목]")
    print("-" * 45)
    result = trader.get_balance()
    if result:
        holdings, summary = result
        if holdings:
            for h in holdings:
                sym = h.get('ovrs_pdno', '?')
                qty = h.get('ovrs_cblc_qty', '0')
                buy_avg = h.get('pchs_avg_pric', '0')
                cur = h.get('now_pric2', '0')
                pnl = h.get('frcr_evlu_pfls_amt', '0')
                pnl_rate = h.get('evlu_pfls_rt', '0')
                print(f"  📈 {sym}: {qty}주 | 매입가: ${buy_avg} | 현재가: ${cur} | 손익: ${pnl} ({pnl_rate}%)")
        else:
            print("  📭 보유 종목 없음")

        tot_pnl = summary.get('tot_evlu_pfls_amt', '0') if summary else '0'
        tot_buy = summary.get('frcr_pchs_amt1', '0') if summary else '0'
        print(f"\n  📋 총 매입금액: ${tot_buy}")
        print(f"  📋 총 평가손익: ${tot_pnl}")

    print("\n" + "=" * 55)
    print("🏁 점검 완료!")
