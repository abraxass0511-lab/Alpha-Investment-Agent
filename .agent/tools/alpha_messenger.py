import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# .env 파일 로드 (로컬 테스트용)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        print("❌ 에러: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        return
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ 텔레그램 메시지 전송 성공!")
        else:
            print(f"❌ 전송 실패: {response.text}")
    except Exception as e:
        print(f"❌ 전송 중 오류 발생: {e}")

def report_daily_picks():
    today = datetime.now().strftime("%Y%m%d")
    report_file = f"output_reports/final_picks_{today}.csv"
    
    if os.path.exists(report_file):
        df = pd.read_csv(report_file)
        if not df.empty:
            msg = "🔔 *[대표님! 오늘의 알파 최종 매수 보고서]* 🔔\n\n"
            msg += f"📅 일자: {datetime.now().strftime('%Y-%m-%d')}\n"
            msg += "--------------------------------------\n"
            
            for index, row in df.iterrows():
                msg += f"🚀 *{row['Symbol']}* - {row['Name']}\n"
                msg += f"   - 현재가: ${row['Current Price']}\n"
                msg += f"   - 모멘텀: +{row['Momentum (%)']}% (이평선 대비)\n"
                msg += f"   - AI 심리: {row['Sentiment']} (초호재!)\n\n"
            
            msg += "--------------------------------------\n"
            msg += "💬 *대표님, 이 종목들을 지금 바로 매수할까요?*\n"
            msg += "(승인을 원하시면 아래에 'Approve'라고 답장해주세요!)"
        else:
            msg = "😴 *[오늘의 알파 보고]* \n\n오늘은 '체급+내실+에너지' 조건을 모두 만족하는 종목이 없습니다. 안전하게 현금을 보유하십시오! 🛡️"
    else:
        # 만약 최종 픽 파일이 없다면, 시장 상황이 안 좋아서 컷된 경우임
        msg = "😴 *[오늘의 알파 보고]* \n\n현재 50일 이동평균선 아래에 있는 종목이 대다수입니다. 안전하게 현금을 보유하십시오! 🛡️"

    send_telegram_message(msg)

if __name__ == "__main__":
    report_daily_picks()
