import os
import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class AlphaTrader:
    def __init__(self):
        # 깃허브 시크릿(금고)에서 정보 가져오기
        self.app_key = os.getenv("KIS_APP_KEY")
        self.secret_key = os.getenv("KIS_SECRET_KEY")
        self.account_no = os.getenv("KIS_ACCOUNT_NO")
        self.base_url = os.getenv("KIS_BASE_URL") # https://openapivts.koreainvestment.com:29443
        
        self.access_token = None
        self.token_expiry = None

    def get_access_token(self):
        """은행에서 24시간짜리 입장권(Token)을 받아옵니다."""
        # 이미 입장권이 있고 시간이 남았다면 그대로 사용
        if self.access_token and self.token_expiry > datetime.now():
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
                # 유효기간 저장 (보통 24시간)
                print("✅ KIS 입장권(Token) 발급 성공!")
                return self.access_token
            else:
                print(f"❌ 입장권 발급 실패: {data}")
                return None
        except Exception as e:
            print(f"🚨 KIS 연결 에러: {e}")
            return None

    def get_balance(self):
        """가짜 주머니(모의투자 계좌)에 돈이 얼마나 있는지 확인합니다."""
        token = self.get_access_token()
        if not token: return None

        # 해외주식 잔고 조회 주소 (모의/실전 동일)
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
        
        # 은행에 보낼 '나 이런 사람이야' 증명서
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "VRPP7640R" # 모의투자용 잔고조회 코드
        }
        
        # 계좌번호가 10자리라면 앞 8자리와 뒤 2자리를 나눕니다.
        # KIS 계좌번호 형식: 12345678-01 -> 12345678, 01
        acc_no_prefix = self.account_no[:8]
        acc_no_suffix = self.account_no[-2:]

        params = {
            "CANO": acc_no_prefix,
            "ACNT_PRDT_CD": acc_no_suffix,
            "WCRC_FRCR_DVSN_CD": "01", # 원화(01) 또는 외화(02)
            "NATN_CD": "840" # 미국(840)
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                return data['output1']
            else:
                print(f"❌ 잔고 조회 실패: {data.get('msg1')}")
                return None
        except Exception as e:
            print(f"🚨 잔고 조회 에러: {e}")
            return None

    def buy_order(self, symbol, quantity, price):
        """로봇이 실제로 주식을 삽니다! (시장가 주문)"""
        token = self.get_access_token()
        if not token: return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "VRPP1002U" # 해외주식 모의투자 매수 코드
        }

        acc_no_prefix = self.account_no[:8]
        acc_no_suffix = self.account_no[-2:]

        payload = {
            "CANO": acc_no_prefix,
            "ACNT_PRDT_CD": acc_no_suffix,
            "OVRS_EXCH_CD": "NAS", # 나스닥(NAS) 또는 뉴욕(NYS)
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ITM_AMES": str(price),
            "ORD_DVSN": "00" # 지정가(00)
        }

        try:
            res = requests.post(url, headers=headers, json=payload)
            data = res.json()
            if data.get('rt_cd') == '0':
                print(f"🎯 [매수 성공] {symbol} {quantity}주 주문 완료!")
                return True
            else:
                print(f"❌ [매수 실패] {data.get('msg1')}")
                return False
        except Exception as e:
            print(f"🚨 매수 에러: {e}")
            return False

if __name__ == "__main__":
    # 간단한 연결 테스트
    trader = AlphaTrader()
    print("🏦 KIS 연결 테스트 시작...")
    balance = trader.get_balance()
    if balance:
        print(f"💰 내 계좌 잔고 확인 성공!")
        print(f"💵 예수금(달러): ${balance[0].get('frcr_dn_sum_amt', '0')}")
    else:
        print("❌ 연결 실패. App Key와 Secret Key를 다시 확인해 주세요.")
