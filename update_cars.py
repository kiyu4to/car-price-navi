
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

URL = "https://www.suzuki.co.jp/car/hustler/"
ROBOTS = "https://www.suzuki.co.jp/robots.txt"
AGENT = "CarPriceNavi"

headers = {
    "User-Agent": AGENT
}

# 自動取得の許可を確認
response = requests.get(
    ROBOTS,
    headers=headers,
    timeout=30
)
response.raise_for_status()

robots = RobotFileParser()
robots.parse(response.text.splitlines())

if not robots.can_fetch(AGENT, URL):
    raise RuntimeError("自動取得が許可されていません")

# メーカー公式HPを取得
response = requests.get(
    URL,
    headers=headers,
    timeout=30
)

response.raise_for_status()

soup = BeautifulSoup(response.content, "html.parser")

for tag in soup(["script", "style", "noscript"]):
    tag.decompose()

text = soup.get_text(separator=" ", strip=True)
text = unicodedata.normalize("NFKC", text)
text = re.sub(r"\s+", " ", text)

# 金額の候補を抽出
pattern = r"([0-9]{1,3}(?:,[0-9]{3})+)\s*円"
candidates = []

for match in re.finditer(pattern, text):
    price = int(match.group(1).replace(",", ""))

    if 1000000 <= price <= 5000000:
        start = max(0, match.start() - 180)
        end = min(len(text), match.end() + 100)

        candidates.append({
            "price": price,
            "context": text[start:end]
        })

if not candidates:
    raise RuntimeError("価格情報を取得できませんでした")

jst = timezone(timedelta(hours=9))

result = {
    "maker": "スズキ",
    "model": "ハスラー",
    "source_url": URL,
    "checked_at": datetime.now(jst).isoformat(),
    "status": "review_required",
    "candidates": candidates
}

print(json.dumps(
    result,
    ensure_ascii=False,
    indent=2
))

print("価格候補取得件数:", len(candidates))
print("取得テスト完了")


# グレードと価格の対応関係を調査
print("=== GRADE STRUCTURE START ===")

seen = set()

for node in soup.find_all(string=True):
    value = unicodedata.normalize("NFKC", str(node))

    if not re.search(
        r"\d{1,3}(?:,\d{3}){2}", value
    ):
        continue

    parent = node.parent
    for level in range(5):
        if parent is None:
            break

        content = parent.get_text(" ", strip=True)

        if len(content) > 1200:
            break

        classes = " ".join(parent.get("class", []))
        key = (classes, content)

        if key not in seen:
            seen.add(key)
            print("LEVEL:", level)
            print("TAG:", parent.name)
            print("CLASS:", classes)
            print("TEXT:", content)

        parent = parent.parent

print("=== GRADE STRUCTURE END ===")
