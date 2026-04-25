import os
import re
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ────────────────────────────────────────────
# 환경변수
# ────────────────────────────────────────────
SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_KEY         = os.environ["SUPABASE_KEY"]
TELEGRAM_TOKEN       = os.environ["TELEGRAM_TOKEN_DOLLAR"]
TELEGRAM_CHAT_ID     = os.environ["TELEGRAM_CHAT_ID_DOLLAR"]

# Supabase 고정 행 ID
CONFIG_ID = "00000000-0000-0000-0000-000000000001"

# KST 기준 점검 제외 시간 (23:30 ~ 00:10)
SKIP_START = (23, 30)
SKIP_END   = (0, 10)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ────────────────────────────────────────────
# 시간 체크 (점검 시간이면 종료)
# ────────────────────────────────────────────
def is_maintenance_time() -> bool:
    kst = datetime.now(timezone(timedelta(hours=9)))
    h, m = kst.hour, kst.minute
    total = h * 60 + m
    skip_s = SKIP_START[0] * 60 + SKIP_START[1]  # 23:30 = 1410
    skip_e = SKIP_END[0]   * 60 + SKIP_END[1]    # 00:10 = 10
    # 자정 걸치므로: 1410 이상 OR 10 이하
    return total >= skip_s or total <= skip_e


# ────────────────────────────────────────────
# 텔레그램 메시지 발송
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
# 텔레그램 새 메시지 가져오기 (offset 방식)
# ────────────────────────────────────────────
def get_new_messages(last_update_id):
    offset = (last_update_id + 1) if last_update_id else None
    params = {"timeout": 0}
    if offset:
        params["offset"] = offset
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
    res = supabase.table("zlotto").select(
        "usd_base_rate, usd_threshold, usd_last_alert_rate, "
        "usd_last_alert_at, usd_last_tg_update_id, usd_active"
    ).eq("id", CONFIG_ID).single().execute()
    return res.data


# ────────────────────────────────────────────
# Supabase 설정 업데이트
# ────────────────────────────────────────────
def update_config(payload: dict):
    supabase.table("zlotto").update(payload).eq("id", CONFIG_ID).execute()


# ────────────────────────────────────────────
# 네이버 금융 USD/KRW 스크래핑
# ────────────────────────────────────────────
def fetch_usd_krw() -> float | None:
    url = "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/marketindex/"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        html = res.text

        # 방법 1: h1.tit 현재가
        match = re.search(r'class="tit"[^>]*>\s*([\d,]+\.?\d*)', html)
        if match:
            rate = float(match.group(1).replace(",", ""))
            if 900 < rate < 2000:
                print(f"✅ 환율 조회 성공 (방법1): {rate}")
                return rate

        # 방법 2: data-value 또는 blind 태그
        match = re.search(r'<span[^>]*class="[^"]*value[^"]*"[^>]*>([\d,]+\.?\d*)<', html)
        if match:
            rate = float(match.group(1).replace(",", ""))
            if 900 < rate < 2000:
                print(f"✅ 환율 조회 성공 (방법2): {rate}")
                return rate

        # 방법 3: 숫자 패턴 직접 탐색
        matches = re.findall(r'(1[0-9]{3}\.\d{2})', html)
        if matches:
            rate = float(matches[0])
            print(f"✅ 환율 조회 성공 (방법3): {rate}")
            return rate

        print("❌ 환율 파싱 실패")
        return None

    except Exception as e:
        print(f"❌ 환율 조회 오류: {e}")
        return None


# ────────────────────────────────────────────
# 텔레그램 명령어 처리
# ────────────────────────────────────────────
def handle_commands(messages: list, config: dict, current_rate: float | None) -> dict:
    """
    명령어:
      /기준가 1370  → usd_base_rate 설정
      /범위 5       → usd_threshold 설정
      /현재         → 현재 설정 + 환율 답장
      /리셋         → 기준가를 현재 환율로 리셋
      /중지         → usd_active = false
      /시작         → usd_active = true
    """
    updates = {}
    last_update_id = config.get("usd_last_tg_update_id")

    for msg in messages:
        update_id = msg.get("update_id")
        message   = msg.get("message", {})
        text      = message.get("text", "").strip()
        chat_id   = str(message.get("chat", {}).get("id", ""))

        # 본인 채팅방 메시지만 처리
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
            rate_str  = f"{current_rate:,.2f}원" if current_rate else "조회 실패"
            status    = "🟢 활성" if active else "🔴 중지"
            upper     = f"{base + threshold:,.2f}" if base and threshold else "-"
            lower     = f"{base - threshold:,.2f}" if base and threshold else "-"
            send_telegram(
                f"📊 <b>현재 설정</b>\n\n"
                f"상태: {status}\n"
                f"기준가: <b>{base:,.2f}원</b>\n"
                f"변동폭: ±{threshold:.1f}원\n"
                f"알림 조건: {lower}원 이하 or {upper}원 이상\n"
                f"현재 환율: <b>{rate_str}</b>"
            )

        elif text == "/리셋":
            if current_rate:
                updates["usd_base_rate"]       = current_rate
                updates["usd_last_alert_rate"]  = None
                updates["usd_last_alert_at"]    = None
                send_telegram(f"✅ 기준가를 현재 환율 <b>{current_rate:,.2f}원</b>으로 리셋했습니다.")
            else:
                send_telegram("⚠️ 현재 환율 조회 실패로 리셋할 수 없습니다.")

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
def check_and_alert(config: dict, current_rate: float):
    base      = config.get("usd_base_rate")
    threshold = config.get("usd_threshold")

    if not base or not threshold:
        print("⚠️ 기준가 또는 변동폭 미설정")
        return {}

    diff    = current_rate - base
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

    # 알림 후 기준가 자동 리셋
    return {
        "usd_base_rate":      current_rate,
        "usd_last_alert_rate": current_rate,
        "usd_last_alert_at":  datetime.now(timezone.utc).isoformat(),
    }


# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
def main():
    # 1. 점검 시간 체크
    if is_maintenance_time():
        print("🔧 점검 시간 (23:30~00:10) — 종료")
        return

    # 2. Supabase 설정 조회
    config = get_config()
    print(f"⚙️ 설정: {config}")

    # 3. 현재 환율 조회
    current_rate = fetch_usd_krw()
    if current_rate:
        print(f"💵 현재 환율: {current_rate:,.2f}원")
    else:
        print("❌ 환율 조회 실패")

    # 4. 텔레그램 새 메시지 확인 및 명령어 처리
    last_update_id = config.get("usd_last_tg_update_id")
    messages = get_new_messages(last_update_id)
    updates  = handle_commands(messages, config, current_rate)

    # 5. 명령어로 설정이 바뀐 경우 config에도 반영
    merged_config = {**config, **updates}

    # 6. 알림 활성 상태이고 환율 조회 성공 시 조건 판단
    if merged_config.get("usd_active") and current_rate:
        alert_updates = check_and_alert(merged_config, current_rate)
        updates.update(alert_updates)

    # 7. 변경사항 Supabase 저장
    if updates:
        update_config(updates)
        print(f"💾 Supabase 업데이트: {updates}")
    else:
        print("ℹ️ 변경사항 없음")


if __name__ == "__main__":
    main()
