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
        print("❌ Telegram Config Missing! TOKEN={}, CHAT_ID={}".format(bool(TELEGRAM_TOKEN), bool(CHAT_ID)))
        raise RuntimeError("Telegram 설정 누락")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"⚠️ Telegram API 응답: {r.status_code} - {r.text[:200]}")
            # Markdown 파싱 실패 시 plain text로 재시도
            payload_plain = {"chat_id": CHAT_ID, "text": text}
            r2 = requests.post(url, json=payload_plain, timeout=30)
            print(f"   Plain text 재시도: {r2.status_code}")
        else:
            print(f"✅ 텔레그램 발송 성공 (길이: {len(text)}자)")
    except Exception as e:
        print(f"❌ 텔레그램 발송 에러: {e}")
        raise


def get_portfolio_section():
    """보유종목 현황과 예수금을 Cloudflare Worker 경유로 조회합니다."""
    try:
        worker_url = os.getenv("WORKER_URL", "")
        worker_key = os.getenv("WORKER_API_KEY", "alpha-internal")

        if not worker_url:
            return "\n⚠️ Worker URL 미설정\n"

        r = requests.get(
            f"{worker_url}/api/portfolio",
            headers={"Authorization": f"Bearer {worker_key}"},
            timeout=15,
        )
        if r.status_code != 200:
            return f"\n⚠️ 포트폴리오 조회 실패 (HTTP {r.status_code})\n"

        data = r.json()
        holdings = data.get("holdings", [])
        usd_amt = data.get("buying_power", "0")

        section = "\n━━━━━━━━━━━━━━━━━━\n"
        section += "*💼 포트폴리오 현황*\n"
        section += "━━━━━━━━━━━━━━━━━━\n"
        section += f"💰 예수금(USD): *${usd_amt}*\n\n"

        # 고점 기록 로드 (트레일링 스탑 표시용)
        peak_data = {}
        try:
            peak_path = "output_reports/peak_prices.json"
            if os.path.exists(peak_path):
                with open(peak_path, "r") as f:
                    peak_data = json.load(f)
        except:
            pass

        if holdings:
            total_pnl = 0
            total_eval = 0
            total_invested = 0

            for h in holdings:
                sym = h.get("symbol", "?")
                qty = h.get("qty", 0)
                buy_avg = h.get("buy_avg", 0)
                cur = h.get("current", 0)
                pnl = h.get("pnl_amt", 0)
                pnl_rt = h.get("pnl_rate", 0)

                eval_amt = cur * qty
                total_pnl += pnl
                total_eval += eval_amt
                total_invested += buy_avg * qty

                emoji = "🟢" if pnl >= 0 else "🔴"

                section += f"{emoji} *{sym}*\n"
                section += f"   {qty}주 × ${cur:.2f} | 매입 ${buy_avg:.2f}\n"
                section += f"   평가: ${eval_amt:,.2f} | *{pnl_rt:+.1f}%* ({pnl:+,.2f})\n"

                if sym in peak_data:
                    peak = peak_data[sym].get("peak", cur)
                    stop_line = peak * 0.9
                    section += f"   🛡️ 고점 ${peak:.2f} → 손절선 ${stop_line:.2f}\n"

                section += "\n"

            if total_invested > 0:
                total_rate = (total_pnl / total_invested) * 100
                section += f"💵 총 평가손익: *{total_pnl:+,.2f}* ({total_rate:+.1f}%)\n"
        else:
            section += "📭 보유 종목 없음 (현금 100%)\n"

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

    # 2. 100% 성공 여부 확인 (절대 규칙: 누락 시 보내지 않고 재시도 대기)
    if not meta.get("success_all", False):
        print("🚨 데이터 수집 미완료. 리포트를 보내지 않습니다. 재시도를 대기합니다.")
        return

    # 2-1. 4단계 0건 알림 (정상 스캔이지만 통과 종목 없는 경우)
    s4 = meta.get("step4", meta.get("step12", 0))
    
    if s4 == 0 and meta.get("step3", 0) > 0:
        quota_msg = f"""⚠️ *알파 스캔 알림 (4단계 통과 0건)*

📊 *스캔은 정상 완료됐으나 4단계 통과 종목이 없습니다.*

• 1+2단계(체급+내실): {meta.get('step12', 0)}건 통과
• 3단계(에너지): {meta.get('step3', 0)}건 통과
• 4단계(성장): *0건 통과*
• Finnhub 총 {meta.get('finnhub_calls', 0)}콜

💡 현재 시장에서 성장 기준(Surprise≥10% or Growth≥20%)을 충족하는 종목이 없습니다.
⏱️ 소요시간: {meta.get('elapsed_min', 0)}분 | 엔진: {meta.get('engine', 'V5')}"""
        
        send_telegram_message(quota_msg)
        print("⚠️ 4단계 0건 알림 발송 완료")
        return

    days = ['월', '화', '수', '목', '금', '토', '일']
    
    # 데이터 기준일 = 마지막 거래일 (metadata의 timestamp 또는 계산)
    data_date = None
    ts = meta.get('timestamp', '')
    if ts:
        try:
            data_date = datetime.fromisoformat(ts).date()
        except:
            pass
    
    if data_date is None:
        # 마지막 거래일 계산 (주말/공휴일 제외)
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        market_close = now_utc.replace(hour=21, minute=0)
        d = now_utc if now_utc >= market_close else now_utc - timedelta(days=1)
        while d.weekday() >= 5:  # 주말이면 금요일로
            d -= timedelta(days=1)
        data_date = d.date()
    
    day_name = days[data_date.weekday()]
    date_str = data_date.strftime("%Y-%m-%d")
    
    title = f"📈 *{date_str}({day_name}) 알파 미국주식 정밀 리포트*\n"
    target_info = "📡 *대상: S&P500 종목 전체*\n\n"
    
    # ── 포트폴리오 현황 (최상단 배치) ──
    portfolio_section = get_portfolio_section()

    # V5 메타데이터 호환
    s12 = meta.get('step12', 0)
    s3 = meta.get('step3', 0)
    s4 = meta.get('step4', 0)
    s5 = meta.get('step5', 0)
    s6 = meta.get('step6', 0)

    summary_table = "\n*📊 필터 현황 요약 (통과 기준)*\n"
    summary_table += f"| 1+2단계 | 체급+내실 | {s12}건 | 시총$10B+ ROE15%+ | Finnhub |\n"
    summary_table += f"| 3단계 | 에너지 | {s3}건 | 가격 > 50MA | Finnhub |\n"
    summary_table += f"| 4단계 | 성장 | {s4}건 | Surprise 10%+ | Finnhub |\n"
    summary_table += f"| 5단계 | 심리 | {s5}건 | 점수 0.7+ | Finnhub+Gemini |\n"
    summary_table += f"| 6단계 | Elite 5 | {s6}건 | 12-1 모멘텀 Top5 | Finnhub |\n\n"

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
                # 상세 수치 표시 (대표님 판단용)
                mcap = row.get('MarketCap_M', 0)
                roe_val = row.get('ROE(%)', 0)
                price = row.get('Price', 0)
                ma50 = row.get('MA50', 0)
                surprise = row.get('Surprise(%)', 0)
                eps_g = row.get('EPS_Growth(%)', 0)
                mom = row.get('Momentum_12_1', 0)
                mom_pct = round(mom * 100, 2) if isinstance(mom, float) and abs(mom) < 100 else mom
                
                picks_content += f"   📋 시총: ${mcap:,.0f}M | ROE: {roe_val}%\n"
                picks_content += f"   📈 가격: ${price} | 50MA: ${ma50}\n"
                picks_content += f"   🔬 Surprise: {surprise}% | Growth: {eps_g}%\n"
                picks_content += f"   ⚡ 12-1 모멘텀: {mom_pct}%\n"
                picks_content += f"   • `핵심근거`: {reason}\n\n"
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

    # ── AI 인사이트 (Gemini Flash — 읽기 전용, 숫자 생성 불가) ──
    ai_insight = ""
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key and meta:
            # AI에게 metadata(숫자)를 읽기 전용으로 전달
            insight_prompt = f"""다음은 오늘 S&P500 주식 스캔 결과입니다 (실제 데이터, 수정 불가):

- 1+2단계(시총$10B+ & ROE15%+): {meta.get('step12', meta.get('step1',0))}건 통과
- 3단계(50MA돌파): {meta.get('step3',0)}건 통과
- 4단계(성장): {meta.get('step4',0)}건 통과
- 5단계(심리0.7+): {meta.get('step5',0)}건 통과
- 6단계(최종): {meta.get('step6',0)}건 선정
- 최종 종목: {', '.join(buy_stocks) if buy_stocks else '없음'}

⚠️ 중요 규칙:
1. 위 숫자(통과 건수)는 API 원본이므로 절대 수정하지 마세요
2. "통과하는 종목이 없었으나" 같은 거짓말 금지 — 위 건수가 실제 통과 건수입니다
3. 한국어로 2~3문장 시장 코멘트를 작성하세요. 대표님에게 보고하는 말투로."""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": insight_prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 200},
            }
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                ai_insight = f"*🧠 AI 인사이트 (Gemini Flash)*\n{text}\n\n"
            elif r.status_code == 429:
                ai_insight = ""  # 무료 초과시 인사이트 생략 (보고서는 정상 발송)
    except Exception as e:
        print(f"⚠️ AI 인사이트 생성 에러 (보고서는 정상 발송): {e}")
        ai_insight = ""

    # ── 비고 (절대 규칙 7번: 실제로 모든 데이터를 받았을 때만 "모든 정보 받음" 표시) ──
    if meta.get("success_all", False):
        footer = "📝 _비고 : Finnhub에서 모든 정보 수집 완료_"
    else:
        total = meta.get("total", 503)
        collected = meta.get("step1", 0) + (total - meta.get("step1", 0))  # 수집 시도 수
        footer = f"📝 _비고 : ⚠️ 데이터 일부 누락 발생 (수집 미완료)_"

    # 휴장 안내 (금요일 → 주말 안내, 공휴일 전날 → 공휴일 안내)
    try:
        from us_market_calendar import generate_closure_notice
        closure_notice = generate_closure_notice()
        if closure_notice:
            footer += closure_notice
    except Exception as e:
        print(f"⚠️ 휴장 안내 생성 에러: {e}")

    # 휴장일 캘린더 업데이트 리마인더 (2027년 12월)
    _now = datetime.now()
    if _now.year == 2027 and _now.month == 12:
        footer += "\n\n🚨 *[관리자 알림] 2028년도 미국장 휴장일 달력 업데이트가 필요합니다! 저(알파)에게 갱신을 요청해 주세요.*"

    message = title + target_info + summary_table + analysis_section + rebalance_section + final_result + ai_insight + footer + "\n\n" + portfolio_section
    
    # 3. 로컬 파일 저장 (메모장 대용)
    if not os.path.exists("output_reports"): os.makedirs("output_reports")
    with open(f"output_reports/report_{date_str}.md", "w", encoding="utf-8") as f:
        f.write(message)
    with open("output_reports/latest_report.md", "w", encoding="utf-8") as f:
        f.write(message)

    send_telegram_message(message)
    print(f"✅ 리포트 전송 및 로컬 저장 완료! (report_{date_str}.md)")

if __name__ == "__main__":
    # 메신저는 스캐너가 만든 결과를 발송하는 역할.
    # 휴장일 판단은 워크플로우 cron(월~금)이 담당하므로, 메신저는 결과가 있으면 무조건 발송.
    # 수동 실행(workflow_dispatch) 시에도 정상 동작 보장.
    report_daily_picks()
