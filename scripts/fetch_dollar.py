import os
import re
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ────────────────────────────────────────────
# 환경변수
# ────────────────────────────────────────────
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN_DOLLAR"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID_DOLLAR"]

CONFIG_ID = "config"

# 카카오뱅크 달러박스 보정값
KAKAO_OFFSET = 1.4

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ────────────────────────────────────────────
# 활성 시간 체크 (환율 알림용)
# ────────────────────────────────────────────
def is_active_time() -> bool:
    kst     = datetime.now(timezone(timedelta(hours=9)))
    weekday = kst.weekday()
    h, m    = kst.hour, kst.minute
    total   = h * 60 + m

    if weekday == 5:
        return False
    if weekday == 6:
        return False
    if weekday == 0 and total < 6 * 60:
        return False
    if total >= 23 * 60 + 30 or total <= 10:
        return False
    if 9 * 60 <= total <= 15 * 60 + 30:
        return True
    if 22 * 60 + 30 <= total < 23 * 60 + 30:
        return True
    if 10 < total <= 6 * 60:
        return True
    return False


# ────────────────────────────────────────────
# 텔레그램 발송
# ────────────────────────────────────────────
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        if res.status_code == 200:
            print("✅ 텔레그램 발송 완료")
        else:
            print(f"❌ 텔레그램 발송 실패: {res.text}")
    except Exception as e:
        print(f"❌ 텔레그램 오류: {e}")


# ────────────────────────────────────────────
# 텔레그램 새 메시지 가져오기
# ────────────────────────────────────────────
def get_new_messages(last_update_id):
    params = {"timeout": 0}
    if last_update_id:
        params["offset"] = last_update_id + 1
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params=params, timeout=10
        )
        data = res.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print(f"❌ 텔레그램 메시지 조회 오류: {e}")
    return []


# ────────────────────────────────────────────
# Supabase 설정 조회
# ────────────────────────────────────────────
def get_config():
    res = supabase.table("zdollar").select("*").eq("id", CONFIG_ID).single().execute()
    return res.data


# ────────────────────────────────────────────
# Supabase 설정 업데이트
# ────────────────────────────────────────────
def update_config(payload: dict):
    supabase.table("zdollar").update(payload).eq("id", CONFIG_ID).execute()


# ────────────────────────────────────────────
# 네이버 금융 USD/KRW 스크래핑 + 카카오 보정
# ────────────────────────────────────────────
def fetch_usd_krw():
    url = "https://finance.naver.com/marketindex/exchangeList.naver?type=R"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://finance.naver.com/marketindex/"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        html = res.text
        match = re.search(
            r'FX_USDKRW.*?class="sale">([\d,]+\.?\d*)',
            html, re.DOTALL
        )
        if match:
            rate = float(match.group(1).replace(",", ""))
            if 900 < rate < 2000:
                adjusted = round(rate + KAKAO_OFFSET, 2)
                print(f"✅ 환율 조회 성공: 네이버={rate}원 → 카카오 기준={adjusted}원 (+{KAKAO_OFFSET}원 보정)")
                return adjusted
        print("❌ 환율 파싱 실패")
        return None
    except Exception as e:
        print(f"❌ 환율 조회 오류: {e}")
        return None


# ────────────────────────────────────────────
# 텔레그램 명령어 처리
# ────────────────────────────────────────────
def handle_commands(messages: list, config: dict, current_rate) -> dict:
    updates = {}
    last_update_id = config.get("usd_last_tg_update_id")

    for msg in messages:
        update_id = msg.get("update_id")
        message   = msg.get("message", {})
        text      = message.get("text", "").strip()
        chat_id   = str(message.get("chat", {}).get("id", ""))

        if chat_id != str(TELEGRAM_CHAT_ID):
            last_update_id = update_id
            continue

        print(f"📩 명령어 수신: {text}")

        if text.startswith("/기준가"):
            try:
                val = float(text.split()[1])
                updates["usd_base_rate"] = val
                send_telegram(f"✅ 기준가를 <b>{val:,.2f}원</b>으로 설정했습니다.")
            except:
                send_telegram("⚠️ 사용법: /기준가 1370")

        elif text.startswith("/범위"):
            try:
                val = float(text.split()[1])
                updates["usd_threshold"] = val
                send_telegram(f"✅ 변동폭을 <b>±{val:.1f}원</b>으로 설정했습니다.")
            except:
                send_telegram("⚠️ 사용법: /범위 5")

        elif text == "/현재":
            base      = updates.get("usd_base_rate", config.get("usd_base_rate"))
            threshold = updates.get("usd_threshold", config.get("usd_threshold"))
            active    = config.get("usd_active")
            active_str = "🟢 활성" if is_active_time() else "⏸ 비활성 시간대"
            alarm_str  = "🟢 켜짐" if active else "🔴 꺼짐"
            rate_str   = f"{current_rate:,.2f}원" if current_rate else "비활성 시간대 (조회 안함)"
            if base and threshold:
                upper = f"{base + threshold:,.2f}"
                lower = f"{base - threshold:,.2f}"
                cond  = f"{lower}원 이하 or {upper}원 이상"
            else:
                cond = "미설정"
            send_telegram(
                f"📊 <b>현재 설정</b>\n\n"
                f"시간대: {active_str}\n"
                f"알림: {alarm_str}\n"
                f"기준가: <b>{base:,.2f}원</b>\n"
                f"변동폭: ±{threshold:.1f}원\n"
                f"알림 조건: {cond}\n"
                f"현재 환율: <b>{rate_str}</b>\n"
                f"<i>(카카오뱅크 기준 +{KAKAO_OFFSET}원 보정 적용)</i>"
            )

        elif text == "/리셋":
            if current_rate:
                updates["usd_base_rate"]       = current_rate
                updates["usd_last_alert_rate"]  = None
                updates["usd_last_alert_at"]    = None
                send_telegram(f"✅ 기준가를 현재 환율 <b>{current_rate:,.2f}원</b>으로 리셋했습니다.")
            else:
                send_telegram("⚠️ 비활성 시간대라 환율 조회 안 함. 활성 시간에 /리셋 하거나 /기준가 직접 입력하세요.")

        elif text == "/중지":
            updates["usd_active"] = False
            send_telegram("🔴 환율 알림을 <b>중지</b>했습니다.")

        elif text == "/시작":
            updates["usd_active"] = True
            send_telegram("🟢 환율 알림을 <b>시작</b>했습니다.")

        last_update_id = update_id

    if last_update_id:
        updates["usd_last_tg_update_id"] = last_update_id

    return updates


# ────────────────────────────────────────────
# 환율 알림 조건 판단
# ────────────────────────────────────────────
def check_and_alert(config: dict, current_rate: float) -> dict:
    base      = config.get("usd_base_rate")
    threshold = config.get("usd_threshold")

    if not base or not threshold:
        print("⚠️ 기준가 또는 변동폭 미설정")
        return {}

    diff     = current_rate - base
    abs_diff = abs(diff)

    print(f"📈 기준가: {base}, 현재: {current_rate}, 차이: {diff:+.2f}원")

    if abs_diff < threshold:
        print(f"✅ 변동폭 미달 ({abs_diff:.2f}원 < {threshold}원) → 알림 없음")
        return {}

    direction = "📈 상승" if diff > 0 else "📉 하락"
    emoji     = "🔴" if diff > 0 else "🔵"
    kst       = datetime.now(timezone(timedelta(hours=9)))
    time_str  = kst.strftime("%Y-%m-%d %H:%M KST")

    send_telegram(
        f"{emoji} <b>USD/KRW 환율 {direction} 알림</b>\n\n"
        f"💵 현재 환율: <b>{current_rate:,.2f}원</b>\n"
        f"📊 기준가 대비: <b>{diff:+.2f}원</b>\n"
        f"🎯 변동폭: ±{threshold:.1f}원\n"
        f"⏰ {time_str}\n\n"
        f"<i>기준가가 {current_rate:,.2f}원으로 자동 업데이트됩니다.</i>"
    )

    return {
        "usd_base_rate":       current_rate,
        "usd_last_alert_rate": current_rate,
        "usd_last_alert_at":   datetime.now(timezone.utc).isoformat(),
    }


# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
def main():
    kst = datetime.now(timezone(timedelta(hours=9)))
    print(f"🕐 현재 KST: {kst.strftime('%Y-%m-%d %H:%M (%A)')}")

    active = is_active_time()

    config = get_config()
    print(f"⚙️ 설정: base={config.get('usd_base_rate')}, threshold={config.get('usd_threshold')}, active={config.get('usd_active')}")

    current_rate = None
    if active:
        current_rate = fetch_usd_krw()
        if current_rate:
            print(f"💵 현재 환율 (카카오 기준): {current_rate:,.2f}원")
        else:
            print("❌ 환율 조회 실패")
    else:
        print("⏸ 비활성 시간 — 환율 조회 스킵")

    last_update_id = config.get("usd_last_tg_update_id")
    messages = get_new_messages(last_update_id)
    updates  = handle_commands(messages, config, current_rate)

    merged_config = {**config, **updates}

    if active and merged_config.get("usd_active") and current_rate:
        alert_updates = check_and_alert(merged_config, current_rate)
        updates.update(alert_updates)

    if updates:
        update_config(updates)
        print(f"💾 Supabase 업데이트: {list(updates.keys())}")
    else:
        print("ℹ️ 변경사항 없음")


if __name__ == "__main__":
    main()
