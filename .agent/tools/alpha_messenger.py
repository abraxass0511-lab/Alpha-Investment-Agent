import os
import json
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
    
    summary_table = "*📊 필터 현황 요약 (통과 기준)*\n"
    summary_table += "| 구분 | 필터 항목 | 통과 수 | 통과 기준 |\n"
    summary_table += "| :--- | :--- | :--- | :--- |\n"
    summary_table += f"| **1단계** | **체급 (Size)** | {meta.get('step1', 0)}건 | 시총 *$10B+* |\n"
    summary_table += f"| **2단계** | **내실 (Quality)** | {meta.get('step2', 0)}건 | ROE *15%+* |\n"
    summary_table += f"| **3단계** | **에너지 (Momentum)** | {meta.get('step3', 0)}건 | 가격 *> 50MA* |\n"
    summary_table += f"| **4단계** | **성장 (Growth)** | {meta.get('step4', 0)}건 | Surprise *10%* OR Growth *20%* |\n"
    summary_table += f"| **5단계** | **심리 (Sentiment)** | {meta.get('step5', 0)}건 | 점수 *0.7+* |\n"
    summary_table += f"| **6단계** | **기세 (Elite 5)** | {meta.get('step6', 0)}건 | 12-1 모멘텀 상위 5선 |\n\n"

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

    if buy_stocks:
        final_result = f"*🎯 최종 결과*\n • 선정된 {len(buy_stocks)}개 종목에 대해 자산의 *5%* 분산 매수 추천.\n • 대표님 승인 시 자동 집행 대기 중.\n\n"
    else:
        final_result = "*🎯 최종 결과*\n*🛡️ 가디언 조치*: 정밀 필터링(0.7) 기준 미달. **전액 현금 보유 권고.**\n\n"

    footer = "📝 *비고 : 야후, FMP에서 모든 정보 받음*"

    message = title + target_info + summary_table + analysis_section + final_result + footer
    
    # 3. 로컬 파일 저장 (메모장 대용)
    if not os.path.exists("output_reports"): os.makedirs("output_reports")
    with open(f"output_reports/report_{date_str}.md", "w", encoding="utf-8") as f:
        f.write(message)
    with open("output_reports/latest_report.md", "w", encoding="utf-8") as f:
        f.write(message)

    send_telegram_message(message)
    print(f"✅ 리포트 전송 및 로컬 저장 완료! (report_{date_str}.md)")

if __name__ == "__main__":
    report_daily_picks()
