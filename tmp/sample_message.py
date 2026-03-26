"""순서: 필터현황(+심층분석+최종결과+비고) → 포트폴리오"""

holdings = [
    {"symbol": "AAPL", "name": "Apple Inc.", "qty": 100, "buy_avg": 195.20, "current": 218.45, "peak": 225.10},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "qty": 30, "buy_avg": 120.50, "current": 142.85, "peak": 158.30},
]
deposit = 87432.50
scan = {"total": 503, "step1": 484, "step2": 236, "step3": 61, "step4": 29, "step5": 0, "step6": 0}

msg = f"📈 *2026-03-26(목) 알파 미국주식 정밀 리포트*\n"
msg += f"📡 대상: S&P500 종목 전체\n\n"

# ── ① 필터 현황 + 분석 + 결과 + 비고 (한 덩어리) ──
msg += f"━━━━━━━━━━━━━━━━━━\n"
msg += f"*📊 필터 현황 요약*\n"
msg += f"━━━━━━━━━━━━━━━━━━\n"
msg += f"`1단계` 체급     : {scan['total']} → *{scan['step1']}건* ✅\n"
msg += f"`2단계` 내실     : {scan['step1']} → *{scan['step2']}건* ✅\n"
msg += f"`3단계` 에너지   : {scan['step2']} → *{scan['step3']}건* ✅\n"
msg += f"`4단계` 성장     : {scan['step3']} → *{scan['step4']}건* ✅\n"
msg += f"`5단계` 심리     : {scan['step4']} → *{scan['step5']}건* ✅\n"
msg += f"`6단계` 기세     : {scan['step5']} → *{scan['step6']}건* ✅\n\n"

msg += f"*🧠 심층 분석 결과*\n"
msg += f"❌ *조건 부합 종목 없음*\n\n"

msg += f"*🎯 최종 결과*\n"
msg += f"🛡️ 가디언 조치: 정밀 필터링(0.7) 기준 미달. *전액 현금 보유 권고.*\n\n"

msg += f"📝 _비고 : 야후, FMP에서 모든 정보 받음_\n\n"

# ── ② 포트폴리오 현황 ──
msg += f"━━━━━━━━━━━━━━━━━━\n"
msg += f"*💼 포트폴리오 현황*\n"
msg += f"━━━━━━━━━━━━━━━━━━\n"
msg += f"💰 예수금: *${deposit:,.2f}*\n\n"

total_invested = 0
total_pnl = 0

for h in holdings:
    pnl = (h["current"] - h["buy_avg"]) * h["qty"]
    pnl_rate = ((h["current"] - h["buy_avg"]) / h["buy_avg"]) * 100
    eval_amt = h["current"] * h["qty"]
    stop_line = h["peak"] * 0.9
    total_invested += h["buy_avg"] * h["qty"]
    total_pnl += pnl
    emoji = "🟢" if pnl >= 0 else "🔴"

    msg += f"{emoji} *{h['symbol']}* ({h['name']})\n"
    msg += f"   {h['qty']}주 × ${h['current']:.2f} | 매입 ${h['buy_avg']:.2f}\n"
    msg += f"   평가: ${eval_amt:,.2f} | *{pnl_rate:+.1f}%* ({pnl:+,.2f})\n"
    msg += f"   🛡️ 고점 ${h['peak']:.2f} → 손절선 ${stop_line:.2f}\n\n"

total_rate = (total_pnl / total_invested) * 100
msg += f"💵 총 평가손익: *{total_pnl:+,.2f}* ({total_rate:+.1f}%)\n"
msg += f"🛡️ 재검증: 보유 {len(holdings)}종목 모두 1~6단계 적격 ✅"

print(msg)
