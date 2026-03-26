import os
import json
import sys
import pandas as pd
from datetime import datetime
import requests
from dotenv import load_dotenv
import time

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram Config Missing!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)


def get_portfolio_section():
    """보유종목 현황과 예수금을 조회하여 리포트 섹션을 생성합니다."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from alpha_trader import AlphaTrader

        trader = AlphaTrader()

        # 예수금 조회
        deposit = trader.get_deposit()
        buying_power = trader.get_buying_power(symbol="AAPL", price="0")

        # 보유 종목 조회
        balance = trader.get_balance()

        section = "\n*🏦 포트폴리오 현황*\n"
        section += "─────────────────\n"

        # 예수금 정보
        if deposit and deposit.get("output3"):
            tot_asst = deposit["output3"].get("tot_asst_amt", "N/A")
            try:
                tot_val = float(tot_asst)
                section += f"💎 총 자산: ₩{tot_val:,.0f}\n"
            except:
                section += f"💎 총 자산: ₩{tot_asst}\n"

        if buying_power:
            usd_amt = buying_power.get("ord_psbl_frcr_amt", "N/A")
            section += f"💵 USD 매수가능: ${usd_amt}\n"

        # 보유 종목 정보
        if balance:
            holdings, summary = balance
            if holdings:
                section += f"\n*📈 보유 종목 ({len(holdings)}개)*\n"
                total_pnl = 0
                for h in holdings:
                    sym = h.get('ovrs_pdno', '?')
                    qty = h.get('ovrs_cblc_qty', '0')
                    buy_avg = h.get('pchs_avg_pric', '0')
                    cur = h.get('now_pric2', '0')
                    pnl = h.get('frcr_evlu_pfls_amt', '0')
                    pnl_rt = h.get('evlu_pfls_rt', '0')

                    try:
                        pnl_val = float(pnl)
                        total_pnl += pnl_val
                        emoji = "🟢" if pnl_val >= 0 else "🔴"
                    except:
                        emoji = "⚪"

                    section += f"  {emoji} *{sym}*: {qty}주 (${buy_avg} → ${cur}, {pnl_rt}%)\n"

                section += f"\n📊 총 평가손익: *${total_pnl:,.2f}*\n"
            else:
                section += "\n📭 보유 종목 없음 (현금 100%)\n"
        else:
            section += "\n⚠️ 보유 종목 조회 불가\n"

        return section

    except Exception as e:
        print(f"⚠️ 포트폴리오 조회 에러: {e}")
        return "\n⚠️ 포트폴리오 정보 조회 실패\n"


def report_daily_picks():
    picks_file = "output_reports/final_picks_latest.csv"
    
    # 1. 메타데이터 읽기
    try:
        with open("output_reports/metadata.json", "r") as f:
            meta = json.load(f)
    except:
        print("❌ 메타데이터 없음. 전수 조사가 완료되지 않았을 수 있습니다.")
        return

    # 2. 100% 성공 여부 확인 (유저 요청 반영)
    if not meta.get("success_all", False):
        print("🚨 야후 데이터 100% 수집 실패. 리포트 전송을 중단하고 재시도를 대기합니다.")
        return

    days = ['월', '화', '수', '목', '금', '토', '일']
    now = datetime.now()
    day_name = days[now.weekday()]
    date_str = now.strftime("%Y-%m-%d")
    
    title = f"📈 *{date_str}({day_name}) 알파 미국주식 정밀 리포트*\n"
    target_info = "📡 *대상: S&P500 종목 전체*\n\n"
    
    # ── 포트폴리오 현황 (최상단 배치) ──
    portfolio_section = get_portfolio_section()

    summary_table = "\n*📊 필터 현황 요약 (통과 기준)*\n"
    summary_table += "| 구분 | 필터 항목 | 통과 수 | 통과 기준 | 소스 |\n"
    summary_table += "| :--- | :--- | :--- | :--- | :--- |\n"
    summary_table += f"| **1단계** | **체급 (Size)** | {meta.get('step1', 0)}건 | 시총 *$10B+* | Yahoo |\n"
    summary_table += f"| **2단계** | **에너지 (Momentum)** | {meta.get('step2', 0)}건 | 가격 *> 50MA* | Yahoo |\n"
    summary_table += f"| **3단계** | **내실 (Quality)** | {meta.get('step3', 0)}건 | ROE *15%+* | FMP |\n"
    summary_table += f"| **4단계** | **성장 (Growth)** | {meta.get('step4', 0)}건 | Surprise *10%* OR Growth *20%* | FMP |\n"
    summary_table += f"| **5단계** | **심리 (Sentiment)** | {meta.get('step5', 0)}건 | 점수 *0.7+* | Finnhub |\n"
    summary_table += f"| **6단계** | **기세 (Elite 5)** | {meta.get('step6', 0)}건 | 12-1 모멘텀 상위 5선 | FMP |\n\n"

    analysis_section = "*🧠 심층 분석 결과 (최종 승인 대기)*\n"
    buy_stocks = []
    
    if os.path.exists(picks_file) and os.path.getsize(picks_file) > 50:
        df = pd.read_csv(picks_file)
        if 'Sentiment' in df.columns:
            df_final = df[df['Sentiment'] >= 0.7]
        else:
            df_final = pd.DataFrame()
            
        if df_final.empty:
            analysis_section += "❌ *5단계 통과 종목(0.7점 이상) 없음*\n\n"
        else:
            picks_content = ""
            for i, row in df_final.iterrows():
                symbol = row['Symbol']
                name = row.get('Name', symbol)
                reason = row.get('Reason', '분석 중')
                buy_stocks.append(symbol)
                picks_content += f"*{len(buy_stocks)}. {name} ({symbol})* 🔥 [BUY]\n"
                picks_content += f"   • `모델`: Flash ⚡ / Pro 🧠\n"
                picks_content += f"   • `핵심근거`: {reason} - Pro 🧠\n\n"
            analysis_section += picks_content
    else:
        analysis_section += "❌ *조건 부합 종목 없음*\n\n"

    # ── 리밸런싱 추천 (보유종목 재검증 결과) ──
    rebalance_section = ""
    has_rebalance = False
    try:
        rebal_path = "output_reports/rebalance_recommendations.json"
        if os.path.exists(rebal_path):
            with open(rebal_path, "r", encoding="utf-8") as f:
                rebal = json.load(f)

            sell_recs = rebal.get("sell", [])
            buy_recs = rebal.get("buy", [])

            if sell_recs or buy_recs:
                has_rebalance = True
                rebalance_section = "\n*⚖️ 리밸런싱 추천 (승인 필요)*\n"
                rebalance_section += "─────────────────\n"

            # 매도 추천
            if sell_recs:
                rebalance_section += f"\n🔻 *매도 추천: {len(sell_recs)}종목*\n"
                for s in sell_recs:
                    sym = s["symbol"]
                    pnl = s.get("pnl_rate", 0)
                    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                    reasons = " / ".join(s.get("reasons", []))
                    rebalance_section += f"  {pnl_emoji} *{sym}* (수익률: {pnl:+.1f}%)\n"
                    rebalance_section += f"     탈락 사유: _{reasons}_\n\n"

            # 매수 추천
            if buy_recs:
                rebalance_section += f"🟢 *신규 매수 추천: {len(buy_recs)}종목*\n"
                for b in buy_recs:
                    sym = b["symbol"]
                    name = b.get("name", sym)
                    reason = b.get("reason", "기준 통과")
                    rebalance_section += f"  📈 *{name} ({sym})*\n"
                    rebalance_section += f"     근거: _{reason}_\n\n"

    except Exception as e:
        print(f"⚠️ 리밸런싱 데이터 로드 에러: {e}")

    # ── 최종 결과 + 승인 요청 ──
    if has_rebalance:
        sell_count = len(rebal.get("sell", []))
        buy_count = len(rebal.get("buy", []))
        actions = []
        if sell_count > 0:
            actions.append(f"매도 {sell_count}종목")
        if buy_count > 0:
            actions.append(f"매수 {buy_count}종목")
        action_str = " + ".join(actions)

        final_result = f"*🎯 최종 결과: {action_str} 변경 추천*\n"
        final_result += " • \"승인\" → 매도/매수 자동 집행\n"
        final_result += " • \"반려\" → 현재 포트폴리오 유지\n\n"
    elif buy_stocks:
        final_result = f"*🎯 최종 결과*\n • 선정된 {len(buy_stocks)}개 종목에 대해 자산의 *5%* 분산 매수 추천.\n"
        final_result += " • \"승인\" → 자동 매수 / \"반려\" → 매수 취소\n\n"
    else:
        final_result = "*🎯 최종 결과*\n*🛡️ 가디언 조치*: 정밀 필터링(0.7) 기준 미달. **전액 현금 보유 권고.**\n\n"

    footer = "📝 *비고 : 야후, FMP에서 모든 정보 받음*"

    # 휴장 안내 (금요일 → 주말 안내, 공휴일 전날 → 공휴일 안내)
    try:
        from us_market_calendar import generate_closure_notice
        closure_notice = generate_closure_notice()
        if closure_notice:
            footer += closure_notice
    except Exception as e:
        print(f"⚠️ 휴장 안내 생성 에러: {e}")

    message = title + target_info + portfolio_section + summary_table + analysis_section + rebalance_section + final_result + footer
    
    # 3. 로컬 파일 저장 (메모장 대용)
    if not os.path.exists("output_reports"): os.makedirs("output_reports")
    with open(f"output_reports/report_{date_str}.md", "w", encoding="utf-8") as f:
        f.write(message)
    with open("output_reports/latest_report.md", "w", encoding="utf-8") as f:
        f.write(message)

    send_telegram_message(message)
    print(f"✅ 리포트 전송 및 로컬 저장 완료! (report_{date_str}.md)")

if __name__ == "__main__":
    # 미국 장 개장일 체크
    from us_market_calendar import is_trading_day
    if not is_trading_day():
        print("📅 오늘은 미국 시장 휴장일입니다. 리포트를 건너뜁니다.")
        exit(0)

    report_daily_picks()
