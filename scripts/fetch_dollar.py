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

urls = [
    "https://m.search.naver.com/search.naver?query=%EB%8B%AC%EB%9F%AC%ED%99%98%EC%9C%A8",
    "https://finance.naver.com/marketindex/exchangeList.naver?type=R",
    "https://m.stock.naver.com/front-api/v2/marketIndex/exchange?category=exchange&page=1&pageSize=10",
]

for url in urls:
    print(f"\n=== URL: {url} ===")
    try:
        res = requests.get(url, headers=headers, timeout=10)
        html = res.text
        print(f"상태코드: {res.status_code}, 길이: {len(html)}")
        matches = re.findall(r'1[0-9]{3}\.\d{2}', html)
        print(f"1000~2000 숫자: {matches[:10]}")
        # 1477 근처 값 찾기
        near = [m for m in matches if 1470 <= float(m) <= 1490]
        print(f"1470~1490 범위: {near}")
    except Exception as e:
        print(f"오류: {e}")
