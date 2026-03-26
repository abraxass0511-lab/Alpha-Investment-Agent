"""
us_market_calendar.py — 미국 주식시장 개장/휴장 관리

NYSE 공식 휴장일 기반으로:
  - 오늘이 거래일인지 확인
  - 다음 거래일이 언제인지 반환
  - 휴장 안내 메시지 생성
"""

from datetime import datetime, timedelta, date

# ═══════════════════════════════════════════════════════
# NYSE 공식 휴장일 (2026~2027)
# 매년 말에 다음 해 일정을 추가하면 됩니다.
# ═══════════════════════════════════════════════════════
US_HOLIDAYS = {
    # 2026년
    date(2026, 1, 1):   "신정 (New Year's Day)",
    date(2026, 1, 19):  "마틴 루터 킹 주니어의 날 (MLK Day)",
    date(2026, 2, 16):  "대통령의 날 (Presidents' Day)",
    date(2026, 4, 3):   "성금요일 (Good Friday)",
    date(2026, 5, 25):  "현충일 (Memorial Day)",
    date(2026, 6, 19):  "준틴스 (Juneteenth)",
    date(2026, 7, 3):   "독립기념일 대체휴일 (Independence Day Observed)",
    date(2026, 9, 7):   "노동절 (Labor Day)",
    date(2026, 11, 26): "추수감사절 (Thanksgiving Day)",
    date(2026, 12, 25): "크리스마스 (Christmas Day)",

    # 2027년
    date(2027, 1, 1):   "신정 (New Year's Day)",
    date(2027, 1, 18):  "마틴 루터 킹 주니어의 날 (MLK Day)",
    date(2027, 2, 15):  "대통령의 날 (Presidents' Day)",
    date(2027, 3, 26):  "성금요일 (Good Friday)",
    date(2027, 5, 31):  "현충일 (Memorial Day)",
    date(2027, 6, 18):  "준틴스 대체휴일 (Juneteenth Observed)",
    date(2027, 7, 5):   "독립기념일 대체휴일 (Independence Day Observed)",
    date(2027, 9, 6):   "노동절 (Labor Day)",
    date(2027, 11, 25): "추수감사절 (Thanksgiving Day)",
    date(2027, 12, 24): "크리스마스 대체휴일 (Christmas Observed)",
}


def is_trading_day(check_date=None):
    """오늘(또는 지정일)이 미국 주식시장 거래일인지 확인합니다."""
    if check_date is None:
        check_date = date.today()
    elif isinstance(check_date, datetime):
        check_date = check_date.date()

    # 주말 체크
    if check_date.weekday() >= 5:  # 5=토, 6=일
        return False

    # 공휴일 체크
    if check_date in US_HOLIDAYS:
        return False

    return True


def get_holiday_name(check_date):
    """해당 날짜의 공휴일 이름을 반환합니다."""
    if isinstance(check_date, datetime):
        check_date = check_date.date()
    return US_HOLIDAYS.get(check_date, None)


def get_next_trading_day(from_date=None):
    """다음 거래일을 반환합니다."""
    if from_date is None:
        from_date = date.today()
    elif isinstance(from_date, datetime):
        from_date = from_date.date()

    next_day = from_date + timedelta(days=1)
    while not is_trading_day(next_day):
        next_day += timedelta(days=1)

    return next_day


def get_non_trading_days_ahead(from_date=None):
    """
    오늘 이후 다음 거래일까지의 휴장일 목록을 반환합니다.
    금요일이면 → [(토요일, "주말"), (일요일, "주말")]
    공휴일 전날이면 → [(공휴일, "공휴일명")]
    """
    if from_date is None:
        from_date = date.today()
    elif isinstance(from_date, datetime):
        from_date = from_date.date()

    closed_days = []
    check = from_date + timedelta(days=1)
    next_trading = get_next_trading_day(from_date)

    while check < next_trading:
        if check.weekday() >= 5:
            closed_days.append((check, "주말"))
        elif check in US_HOLIDAYS:
            closed_days.append((check, US_HOLIDAYS[check]))
        check += timedelta(days=1)

    return closed_days


def generate_closure_notice(from_date=None):
    """
    휴장 안내 메시지를 생성합니다.
    - 금요일 → "토,일은 휴장입니다. 다음주 월요일에 보고드리겠습니다."
    - 공휴일 전날 → "1/1일은 신정으로 휴장입니다. 1/2일에 보고드리겠습니다."
    - 일반 평일 → None (안내 불필요)
    """
    if from_date is None:
        from_date = date.today()
    elif isinstance(from_date, datetime):
        from_date = from_date.date()

    closed_days = get_non_trading_days_ahead(from_date)
    if not closed_days:
        return None  # 내일도 거래일 → 안내 불필요

    next_trading = get_next_trading_day(from_date)
    days_kr = ['월', '화', '수', '목', '금', '토', '일']
    next_day_str = f"{next_trading.month}/{next_trading.day}({days_kr[next_trading.weekday()]})"

    # 공휴일이 포함되어 있는지 확인
    holidays_in_gap = [(d, name) for d, name in closed_days if name != "주말"]

    if holidays_in_gap:
        # 공휴일 안내
        holiday_notices = []
        for hd, hname in holidays_in_gap:
            holiday_notices.append(f"{hd.month}/{hd.day}일은 *{hname}*으로 휴장")
        notice = ", ".join(holiday_notices)
        return f"\n📅 _{notice}입니다. {next_day_str}에 보고드리겠습니다._"

    elif from_date.weekday() == 4:
        # 금요일 → 주말 안내
        return f"\n📅 _토, 일은 휴장입니다. 다음주 {next_day_str}에 보고드리겠습니다._"

    return None


# 테스트
if __name__ == "__main__":
    today = date.today()
    print(f"오늘: {today} ({'거래일' if is_trading_day() else '휴장'})")
    print(f"다음 거래일: {get_next_trading_day()}")

    notice = generate_closure_notice()
    if notice:
        print(f"안내: {notice}")
    else:
        print("안내: 내일도 거래일입니다.")
