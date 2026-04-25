import os
import re
import requests

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN_DOLLAR"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID_DOLLAR"]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.naver.com"
}

url = "https://search.naver.com/search.naver?ie=UTF-8&query=%EB%8B%AC%EB%9F%AC%ED%99%98%EC%9C%A8&sm=chr_hty"
res = requests.get(url, headers=headers, timeout=10)
html = res.text

print(f"=== HTTP 상태코드: {res.status_code} ===")
print(f"=== HTML 길이: {len(html)} ===")

# 1000~2000 사이 숫자 패턴 전부 출력
matches = re.findall(r'1[0-9]{3}[.,]\d{2}', html)
print("\n=== 1000~2000 범위 숫자 전체 ===")
for m in matches:
    print(m)

# HTML 앞부분
print("\n=== HTML 앞 500자 ===")
print(html[:500])

# 환율 키워드 주변
for keyword in ["환율", "USD", "KRW", "달러"]:
    idx = html.find(keyword)
    if idx > 0:
        print(f"\n=== '{keyword}' 주변 HTML ===")
        print(html[max(0, idx-100):idx+300])
        break
