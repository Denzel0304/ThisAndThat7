import os
import re
import requests

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN_DOLLAR"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID_DOLLAR"]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com"
}

# finance.naver.com/exchangeList HTML 내용 확인
url = "https://finance.naver.com/marketindex/exchangeList.naver?type=R"
res = requests.get(url, headers=headers, timeout=10)
html = res.text

print(f"상태코드: {res.status_code}")
print(f"HTML 전체:\n{html[:3000]}")
