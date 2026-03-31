"""
alpha_ai_chat.py — 에이전트 알파 AI 대화 엔진

대표님의 자유로운 질문에 맥락을 파악하고 답변합니다.
- 스캔 데이터, 포트폴리오, 센티먼트 등 실제 데이터를 참조
- Google Gemini API를 사용
"""

import os
import sys
import json
import glob
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

sys.path.insert(0, os.path.dirname(__file__))

# ═══════════════════════════════════════════════════════
# 컨텍스트 수집 (실제 데이터를 AI에게 제공)
# ═══════════════════════════════════════════════════════
def gather_context():
    """현재 알파 에이전트가 가진 모든 데이터를 수집합니다."""
    context = {}

    # 1. 스캔 메타데이터
    try:
        with open("output_reports/metadata.json", "r") as f:
            context["scan_metadata"] = json.load(f)
    except:
        context["scan_metadata"] = None

    # 2. 최종 픽 (6단계 통과 종목)
    try:
        import pandas as pd
        picks_path = "output_reports/final_picks_latest.csv"
        if os.path.exists(picks_path) and os.path.getsize(picks_path) > 50:
            df = pd.read_csv(picks_path)
            context["final_picks"] = df.to_dict(orient="records")
        else:
            context["final_picks"] = []
    except:
        context["final_picks"] = []

    # 3. 센티먼트 데이터
    try:
        import pandas as pd
        sent_path = "output_reports/sentiment_all_latest.csv"
        if os.path.exists(sent_path):
            df = pd.read_csv(sent_path)
            context["sentiment_data"] = df.to_dict(orient="records")
        else:
            context["sentiment_data"] = []
    except:
        context["sentiment_data"] = []

    # 4. 포트폴리오 (보유 종목)
    try:
        from alpha_trader import AlphaTrader
        trader = AlphaTrader()
        result = trader.get_balance()
        if result:
            holdings, _ = result
            portfolio = []
            for h in holdings:
                qty = int(float(h.get('ovrs_cblc_qty', '0')))
                if qty <= 0:
                    continue
                portfolio.append({
                    "symbol": h.get('ovrs_pdno', '?'),
                    "qty": qty,
                    "buy_avg": float(h.get('pchs_avg_pric', '0')),
                    "current": float(h.get('now_pric2', '0')),
                    "pnl_rate": float(h.get('evlu_pfls_rt', '0')),
                    "pnl_amt": float(h.get('frcr_evlu_pfls_amt', '0')),
                })
            context["portfolio"] = portfolio

            # 예수금
            buying = trader.get_buying_power(symbol="AAPL", price="0")
            if buying:
                context["deposit_usd"] = buying.get("ord_psbl_frcr_amt", "N/A")
        else:
            context["portfolio"] = []
    except:
        context["portfolio"] = []

    # 5. 트레일링 스탑 고점 기록
    try:
        with open("output_reports/peak_prices.json", "r") as f:
            context["peak_prices"] = json.load(f)
    except:
        context["peak_prices"] = {}

    # 6. 리밸런싱 추천
    try:
        with open("output_reports/rebalance_recommendations.json", "r") as f:
            context["rebalance"] = json.load(f)
    except:
        context["rebalance"] = None

    # 7. 최근 리포트
    try:
        with open("output_reports/latest_report.md", "r", encoding="utf-8") as f:
            context["latest_report"] = f.read()[:2000]
    except:
        context["latest_report"] = None

    return context


# ═══════════════════════════════════════════════════════
# 시스템 프롬프트 (알파 에이전트 페르소나)
# ═══════════════════════════════════════════════════════
SYSTEM_PROMPT = """너는 '에이전트 알파'야. 미국 주식 투자를 전담하는 AI 비서.

## 페르소나
- 대표님(사장님)을 모시는 싹싹하고 친절한 보좌관
- 항상 "대표님"이라고 호칭한다
- 간결하지만 핵심을 정확히 전달한다
- 데이터에 기반한 답변만 한다. 모르면 "확인이 필요합니다"라고 솔직하게 말한다

## 투자 전략 (6단계 필터)
1단계: 체급 (Size) — 시총 $10B 이상
2단계: 내실 (Quality) — ROE 15% 이상
3단계: 에너지 (Momentum) — 주가 > 50일 이동평균선
4단계: 성장 (Growth) — 어닝 서프라이즈 10% 이상 또는 매출 성장률 20% 이상
5단계: 심리 (Sentiment) — MarketAux ML 점수 0.7 이상 AND SMA₅ 0.6 이상 (신규), 0.5 이상 (보유 유지)
6단계: 기세 (Elite) — 12개월-1개월 모멘텀 상위 5종목 선정

## 매도 기준
- 트레일링 스탑: 고점 대비 -10% 하락 시 자동 매도
- 리밸런싱: 1~6단계 중 하나라도 탈락하면 매도 추천

## 답변 규칙
- 실제 데이터가 있으면 반드시 구체적 숫자를 인용한다
- 텔레그램 Markdown 형식으로 답변한다 (*볼드*, _이탤릭_)
- 답변은 300자 이내로 간결하게
- 이모지를 적절히 사용한다
"""


def build_prompt(user_question, context):
    """사용자 질문 + 컨텍스트를 결합하여 프롬프트를 만듭니다."""
    ctx_text = f"\n## 현재 데이터 (오늘 {datetime.now().strftime('%Y-%m-%d')})\n\n"

    if context.get("scan_metadata"):
        m = context["scan_metadata"]
        ctx_text += f"### 스캔 결과\n"
        ctx_text += f"- 1단계(체급): {m.get('step1', 0)}건 통과\n"
        ctx_text += f"- 2단계(내실): {m.get('step2', 0)}건 통과\n"
        ctx_text += f"- 3단계(에너지): {m.get('step3', 0)}건 통과\n"
        ctx_text += f"- 4단계(성장): {m.get('step4', 0)}건 통과\n"
        ctx_text += f"- 5단계(심리): {m.get('step5', 0)}건 통과\n"
        ctx_text += f"- 6단계(기세): {m.get('step6', 0)}건 통과\n\n"

    if context.get("final_picks"):
        ctx_text += f"### 최종 선정 종목\n"
        for p in context["final_picks"]:
            ctx_text += f"- {p.get('Symbol', '?')}: 센티 {p.get('Sentiment', 'N/A')}, 이유: {p.get('Reason', 'N/A')}\n"
        ctx_text += "\n"

    if context.get("portfolio"):
        ctx_text += f"### 보유 종목 (포트폴리오)\n"
        for p in context["portfolio"]:
            ctx_text += f"- {p['symbol']}: {p['qty']}주, 매입 ${p['buy_avg']:.2f}, 현재 ${p['current']:.2f}, 수익률 {p['pnl_rate']:+.1f}%\n"
        ctx_text += f"- 예수금: ${context.get('deposit_usd', 'N/A')}\n\n"

    if context.get("peak_prices"):
        ctx_text += f"### 트레일링 스탑 기록\n"
        for sym, data in context["peak_prices"].items():
            peak = data.get("peak", 0)
            ctx_text += f"- {sym}: 고점 ${peak:.2f}, 손절선 ${peak * 0.9:.2f}\n"
        ctx_text += "\n"

    if context.get("sentiment_data"):
        ctx_text += f"### 센티먼트 데이터 (상위 10개)\n"
        sorted_sent = sorted(context["sentiment_data"], key=lambda x: x.get("Sentiment", 0), reverse=True)[:10]
        for s in sorted_sent:
            ctx_text += f"- {s.get('Symbol', '?')}: 센티 {s.get('Sentiment', 0):.2f}\n"
        ctx_text += "\n"

    return ctx_text + f"\n## 대표님의 질문\n{user_question}"


# ═══════════════════════════════════════════════════════
# Gemini API 호출
# ═══════════════════════════════════════════════════════
def ask_gemini(user_question):
    """Gemini API를 호출하여 답변을 생성합니다."""
    if not GEMINI_API_KEY:
        return "⚠️ AI 엔진(Gemini)이 아직 연결되지 않았습니다. GEMINI_API_KEY를 등록해 주세요."

    context = gather_context()
    user_prompt = build_prompt(user_question, context)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500,
        },
    }

    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            answer = data["candidates"][0]["content"]["parts"][0]["text"]
            return answer.strip()
        elif r.status_code == 429:
            return "⚠️ Gemini AI 무료 제공량을 초과했습니다.\n잠시 후 다시 시도해 주세요, 대표님."
        elif r.status_code == 403:
            return "⚠️ Gemini API 키가 유효하지 않거나 권한이 없습니다."
        else:
            return f"⚠️ AI 응답 에러 (HTTP {r.status_code})"
    except Exception as e:
        return f"⚠️ AI 엔진 에러: {e}"


if __name__ == "__main__":
    # 테스트
    question = "오늘 스캔 결과 어때?"
    print(f"Q: {question}")
    print(f"A: {ask_gemini(question)}")
