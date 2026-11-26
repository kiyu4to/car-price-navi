
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

URL = "https://www.suzuki.co.jp/car/hustler/"
AGENT = "CarPriceNavi"
HEADERS = {"User-Agent": AGENT}

# 自動取得制限の確認
response = requests.get(
    "https://www.suzuki.co.jp/robots.txt",
    headers=HEADERS,
    timeout=30
)
response.raise_for_status()

robots = RobotFileParser()
robots.parse(response.text.splitlines())

if not robots.can_fetch(AGENT, URL):
    raise RuntimeError("自動取得が許可されていません")

# 公式HPの取得
response = requests.get(
    URL,
    headers=HEADERS,
    timeout=30
)
response.raise_for_status()

soup = BeautifulSoup(
    response.content,
    "html.parser"
)

# グレード別・駆動方式別の価格取得
groups = {}

for item in soup.select(
    ".gradePrice__detail__price__item"
):
    text = unicodedata.normalize(
        "NFKC",
        item.get_text(" ", strip=True)
    )

    match = re.search(
        r"(2WD|4WD)\s+CVT\s+([\d,]+)\s*円",
        text
    )

    if not match:
        continue

    drive = match.group(1)
    price = int(match.group(2).replace(",", ""))

    for parent in item.parents:
        content = unicodedata.normalize(
            "NFKC",
            parent.get_text(" ", strip=True)
        )

        grades = set(re.findall(
            r"HYBRID\s+X\s*ターボ|HYBRID\s+X|HYBRID\s+G",
            content
        ))

        if len(grades) > 1:
            break

        if len(grades) == 1:
            grade = next(iter(grades))
            grade = re.sub(r"\s+", " ", grade)
            grade = grade.replace(
                "Xターボ", "X ターボ"
            )

            key = (grade, drive)
            groups.setdefault(key, set())
            groups[key].add(price)
            break

# 必要な6種類が取得できたか確認
expected = {
    (grade, drive)
    for grade in [
        "HYBRID G",
        "HYBRID X",
        "HYBRID X ターボ"
    ]
    for drive in ["2WD", "4WD"]
}

if set(groups) != expected:
    raise RuntimeError(
        "グレード構成が一致しません"
    )

# 車両データの作成
jst = timezone(timedelta(hours=9))
now = datetime.now(jst).isoformat()
cars = []

for (grade, drive), prices in sorted(
    groups.items()
):
    price = min(prices)

    if not 1000000 <= price <= 5000000:
        raise RuntimeError("価格異常")

    cars.append({
        "maker": "スズキ",
        "model": "ハスラー",
        "grade": grade,
        "drive": drive,
        "transmission": "CVT",
        "price": price,
        "price_type": "minimum_listed",
        "price_candidates": sorted(prices),
        "tax_included": True,
        "source_url": URL,
        "updated_at": now,
        "status": "review_required"
    })

# データベースの読み込み
path = Path("cars.json")
data = json.loads(
    path.read_text(encoding="utf-8")
)

# 他の車種のデータは維持
data["cars"] = [
    car for car in data.get("cars", [])
    if not (
        car.get("maker") == "スズキ"
        and car.get("model") == "ハスラー"
    )
]

data["cars"].extend(cars)
data["updated_at"] = now

# 確認用ファイルへ保存
Path("cars_preview.json").write_text(
    json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)

# 実行結果
print("=== PRICE DATABASE ===")

for car in cars:
    print(
        car["grade"],
        car["drive"],
        f'{car["price"]:,}円'
    )

print("登録候補件数:", len(cars))
print("cars_preview.json 作成完了")
print("=== UPDATE COMPLETE ===")
