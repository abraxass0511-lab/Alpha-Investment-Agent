import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

app_key = os.getenv("KIS_APP_KEY")
secret_key = os.getenv("KIS_SECRET_KEY")
account_no = os.getenv("KIS_ACCOUNT_NO")
base_url = os.getenv("KIS_BASE_URL")

# 1. 토큰 발급
print("=" * 50)
print("🏦 KIS 모의투자 계좌 전체 조회")
print("=" * 50)

token_res = requests.post(f"{base_url}/oauth2/tokenP", json={
    "grant_type": "client_credentials",
    "appkey": app_key,
    "appsecret": secret_key
})
token_data = token_res.json()
access_token = token_data.get("access_token")
if not access_token:
    print(f"❌ 토큰 발급 실패: {token_data}")
    exit(1)
print("✅ 토큰 발급 성공")

acc_prefix = account_no[:8]
acc_suffix = account_no[-2:]
headers_base = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {access_token}",
    "appkey": app_key,
    "appsecret": secret_key,
}

# 2. 해외주식 잔고 조회 (보유 종목)
print("\n📊 [1] 해외주식 잔고 (보유 종목)")
print("-" * 40)
headers = {**headers_base, "tr_id": "VTTS3012R"}
params = {
    "CANO": acc_prefix,
    "ACNT_PRDT_CD": acc_suffix,
    "OVRS_EXCG_CD": "NASD",
    "TR_CRCY_CD": "USD",
    "CTX_AREA_FK200": "",
    "CTX_AREA_NK200": ""
}
res = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-balance", headers=headers, params=params)
data = res.json()
if data.get('rt_cd') == '0':
    output1 = data.get('output1', [])
    output2 = data.get('output2', {})
    if output1:
        for h in output1:
            sym = h.get('ovrs_pdno', '?')
            qty = h.get('ovrs_cblc_qty', '0')
            cur_price = h.get('now_pric2', '0')
            pnl = h.get('frcr_evlu_pfls_amt', '0')
            print(f"  📈 {sym}: {qty}주 | 현재가: ${cur_price} | 손익: ${pnl}")
    else:
        print("  📭 보유 종목 없음")
    
    if output2:
        print(f"\n  💰 총 평가금액: ${output2.get('tot_evlu_pfls_amt', 'N/A')}")
        print(f"  📊 외화매입금액: ${output2.get('frcr_pchs_amt1', 'N/A')}")
        print(f"  📊 해외실현손익: ${output2.get('ovrs_rlzt_pfls_amt', 'N/A')}")
        print(f"  📊 해외총손익: ${output2.get('ovrs_tot_pfls', 'N/A')}")
else:
    print(f"  ❌ 잔고 조회 실패: {data.get('msg1')}")

# 3. 매수가능금액 조회
print("\n💵 [2] 매수가능금액 조회")
print("-" * 40)
headers_ps = {**headers_base, "tr_id": "VTTS3007R"}
params_ps = {
    "CANO": acc_prefix,
    "ACNT_PRDT_CD": acc_suffix,
    "OVRS_EXCG_CD": "NASD",
    "OVRS_ORD_UNPR": "100",
    "ITEM_CD": "AAPL"
}
res_ps = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-psamount", headers=headers_ps, params=params_ps)
data_ps = res_ps.json()
if data_ps.get('rt_cd') == '0':
    output = data_ps.get('output', {})
    print(f"  💰 외화주문가능금액: ${output.get('ovrs_ord_psbl_amt', 'N/A')}")
    print(f"  💰 최대주문가능수량: {output.get('max_ord_psbl_qty', 'N/A')}주")
    print(f"  💰 외화예수금: ${output.get('frcr_dncl_amt_2', 'N/A')}")
else:
    print(f"  ❌ 매수가능금액 조회 실패: {data_ps.get('msg1')}")
    print(f"  📋 전체 응답: {json.dumps(data_ps, indent=2, ensure_ascii=False)}")

# 4. 체결기준 현재잔고 조회 (alternative)
print("\n🏦 [3] 체결기준 현재잔고")
print("-" * 40)
headers_pb = {**headers_base, "tr_id": "VTRP6504R"}
params_pb = {
    "CANO": acc_prefix,
    "ACNT_PRDT_CD": acc_suffix,
    "WCRC_FRCR_DVSN_CD": "01",
    "NATN_CD": "840",
    "TR_MKET_CD": "00",
    "INQR_DVSN_CD": "00"
}
res_pb = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance", headers=headers_pb, params=params_pb)
data_pb = res_pb.json()
if data_pb.get('rt_cd') == '0':
    output3 = data_pb.get('output3', {})
    if output3:
        print(f"  💵 외화예수금총액: ${output3.get('frcr_dncl_amt_2', 'N/A')}")
        print(f"  💵 원화예수금총액: ₩{output3.get('frcr_dncl_amt_1', 'N/A')}")
    output2_pb = data_pb.get('output2', [])
    if output2_pb:
        for item in output2_pb:
            print(f"  🏷️ 통화: {item.get('crcy_cd', '?')} | 예수금: {item.get('frcr_dncl_amt_2', 'N/A')}")
else:
    print(f"  ❌ 현재잔고 조회 실패: {data_pb.get('msg1')}")
    print(f"  📋 전체 응답: {json.dumps(data_pb, indent=2, ensure_ascii=False)}")

print("\n" + "=" * 50)
print("🏁 조회 완료!")
