
import json
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.suzuki.co.jp/car/"
AGENT = "CarPriceNavi"
HEADERS = {"User-Agent": AGENT}

CONFIG = [
    {
        "path": "hustler/",
        "models": {
            "ハスラー": [
                "HYBRID G",
                "HYBRID X",
                "HYBRID X ターボ"
            ]
        }
    },
    {
        "path": "spacia/detail/",
        "models": {
            "スペーシア": [
                "HYBRID G",
                "HYBRID X",
                "HYBRID X セーフティプラスパッケージ装着車"
            ],
            "スペーシア カスタム": [
                "HYBRID GS",
                "HYBRID XS",
                "HYBRID XS ターボ"
            ]
        }
    },
    {
        "path": "spacia_gear/detail/",
        "models": {
            "スペーシア ギア": [
                "HYBRID XZ",
                "HYBRID XZ ターボ"
            ]
        }
    }
]

def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(
        r"\s*(?:TURBO|ターボ)",
        " ターボ",
        text,
        flags=re.I
    )
    text = re.sub(
        r"\s*セーフティプラスパッケージ装着車",
        " セーフティプラスパッケージ装着車",
        text
    )
    return text.strip()

session = requests.Session()
session.headers.update(HEADERS)

response = session.get(
    "https://www.suzuki.co.jp/robots.txt",
    timeout=30
)
response.raise_for_status()

robots = RobotFileParser()
robots.parse(response.text.splitlines())

jst = timezone(timedelta(hours=9))
now = datetime.now(jst).isoformat()

preview = Path("cars_preview.json")
original = Path("cars.json")

path = preview if preview.exists() else original

data = json.loads(
    path.read_text(encoding="utf-8")
)

if not isinstance(data.get("cars"), list):
    raise RuntimeError("データベース形式異常")

def fetch_prices(config):

    url = BASE + config["path"]

    if not robots.can_fetch(AGENT, url):
        raise RuntimeError("自動取得制限")

    response = session.get(
        url,
        timeout=30
    )
    response.raise_for_status()

    if not robots.can_fetch(AGENT, response.url):
        raise RuntimeError("取得先の自動取得制限")

    soup = BeautifulSoup(
        response.content,
        "html.parser"
    )

    grade_models = {}

    for model, grades in config["models"].items():
        for grade in grades:
            grade_models[grade] = model

    grades = sorted(
        grade_models,
        key=len,
        reverse=True
    )

    pattern = re.compile(
        "|".join(
            re.escape(g) + r"(?![A-Z])"
            for g in grades
        )
    )

    groups = {}

    # ハスラーと同じ価格表示構造
    if config["path"] == "hustler/":

        for item in soup.select(
            ".gradePrice__detail__price__item"
        ):

            text = normalize(
                item.get_text(" ", strip=True)
            )

            match = re.search(
                r"(2WD|4WD)\s+CVT\s+([\d,]+)\s*円",
                text
            )

            if not match:
                continue

            drive = match.group(1)
            price = int(
                match.group(2).replace(",", "")
            )

            for parent in item.parents:

                content = normalize(
                    parent.get_text(" ", strip=True)
                )

                found = set(
                    pattern.findall(content)
                )

                if len(found) > 1:
                    break

                if len(found) == 1:
                    grade = next(iter(found))
                    groups.setdefault(
                        (grade, drive), set()
                    ).add(price)
                    break

    # スペーシアシリーズの価格比較情報
    else:

        text = normalize(
            soup.get_text(" ", strip=True)
        )

        price_pattern = re.compile(
            "(" + pattern.pattern + ")"
            r"\s*(2WD|4WD)"
            r"\s*[・/]?\s*CVT"
            r"\s*(?:価格\s*[:：]\s*)?"
            r"([\d,]+)\s*円"
        )

        for match in price_pattern.finditer(text):

            grade = match.group(1)
            drive = match.group(2)
            price = int(
                match.group(3).replace(",", "")
            )

            groups.setdefault(
                (grade, drive), set()
            ).add(price)

    expected = {
        (grade, drive)
        for grade in grades
        for drive in ["2WD", "4WD"]
    }

    if set(groups) != expected:
        print("取得済:", sorted(groups))
        print("不足:", sorted(expected - set(groups)))
        raise RuntimeError("グレード構成不一致")

    cars = []

    for (grade, drive), prices in sorted(
        groups.items()
    ):

        price = min(prices)

        if not 1000000 <= price <= 5000000:
            raise RuntimeError("価格異常")

        cars.append({
            "maker": "スズキ",
            "model": grade_models[grade],
            "grade": grade,
            "drive": drive,
            "transmission": "CVT",
            "price": price,
            "price_type": "minimum_listed",
            "price_candidates": sorted(prices),
            "tax_included": True,
            "source_url": url,
            "updated_at": now,
            "status": "review_required"
        })

    return cars


success = 0
failed = 0
total = 0

print("=== PRICE DATABASE ===")

for config in CONFIG:

    try:
        cars = fetch_prices(config)

        models = set(config["models"])

        data["cars"] = [
            car for car in data["cars"]
            if not (
                car.get("maker") == "スズキ"
                and car.get("model") in models
            )
        ]

        data["cars"].extend(cars)

        for car in cars:
            print(
                car["model"],
                car["grade"],
                car["drive"],
                f'{car["price"]:,}円'
            )

        total += len(cars)
        success += 1

        print("取得成功:", len(cars), "件")

    except Exception as error:

        failed += 1
        print("取得失敗:", config["path"])
        print("理由:", str(error))
        print("既存データを維持します")

    time.sleep(3)

if success == 0:
    raise RuntimeError("全取得処理失敗")

data["updated_at"] = now

preview.write_text(
    json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)

print("=== SUMMARY ===")
print("取得成功ページ:", success)
print("取得失敗ページ:", failed)
print("今回取得件数:", total)
print("DB登録総件数:", len(data["cars"]))
print("cars_preview.json 作成完了")
print("=== UPDATE COMPLETE ===")
