
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

# =====================================
# 価格取得対象車種
# =====================================

CONFIG = [
    {
        "path": "hustler/",
        "method": "hustler",
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
        "method": "detail",
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
        "method": "detail",
        "models": {
            "スペーシア ギア": [
                "HYBRID XZ",
                "HYBRID XZ ターボ"
            ]
        }
    },
    {
        "path": "wagonr/",
        "method": "wagonr",
        "models": {
            "ワゴンR": [
                "HYBRID ZX",
                "ZL"
            ]
        }
    },
    {
        "path": "wagonr_smile/",
        "method": "smile",
        "models": {
            "ワゴンR スマイル": [
                "HYBRID X",
                "HYBRID S",
                "G"
            ]
        }
    }
]

# 詳細ページ調査対象
CHECK_MODELS = {
    "アルト": "alto/detail/",
    "ラパン": "lapin/detail/",
    "ジムニー": "jimny/detail/",
    "エブリイワゴン": "everywagon/detail/"
}

# =====================================
# 共通処理
# =====================================

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


def fetch_page(url):

    if not robots.can_fetch(AGENT, url):
        raise RuntimeError("自動取得制限")

    response = session.get(
        url,
        timeout=30,
        allow_redirects=False
    )

    if response.status_code != 200:
        raise RuntimeError(
            "HTTP " + str(response.status_code)
        )

    return BeautifulSoup(
        response.content,
        "html.parser"
    )


# =====================================
# 価格取得
# =====================================

def fetch_prices(config):

    url = BASE + config["path"]

    soup = fetch_page(url)

    method = config["method"]

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
    transmissions = {}

    def add_price(grade, drive, price, transmission):

        price = int(str(price).replace(",", ""))

        if not 1000000 <= price <= 5000000:
            raise RuntimeError("価格異常")

        key = (grade, drive)

        if (
            key in transmissions
            and transmissions[key] != transmission
        ):
            raise RuntimeError("変速機構成不一致")

        groups.setdefault(key, set()).add(price)
        transmissions[key] = transmission

    # ---------------------------------
    # ハスラー
    # ---------------------------------

    if method == "hustler":

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
            price = match.group(2)

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

                    add_price(
                        grade,
                        drive,
                        price,
                        "CVT"
                    )

                    break

    # ---------------------------------
    # スペーシアシリーズ
    # ---------------------------------

    elif method == "detail":

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

            add_price(
                match.group(1),
                match.group(2),
                match.group(3),
                "CVT"
            )

    # ---------------------------------
    # ワゴンR
    # ---------------------------------

    elif method == "wagonr":

        text = normalize(
            soup.get_text(" ", strip=True)
        )

        price_pattern = re.compile(
            r"(?<![A-Z0-9])"
            r"(HYBRID ZX|ZL)(?![A-Z0-9])"
            r"[^。]{0,120}?"
            r"メーカー希望小売価格\s*\(税込\)"
            r"\s*2WD\s*[・/]?\s*"
            r"(CVT(?:\s*/\s*5MT)?)"
            r"\s*車\s*"
            r"([\d,]+)\s*円\s*[~〜]?"
            r"\s*4WD\s*[・/]?\s*"
            r"(CVT(?:\s*/\s*5MT)?)"
            r"\s*車\s*"
            r"([\d,]+)\s*円"
        )

        for match in price_pattern.finditer(text):

            grade = match.group(1)

            trans2 = re.sub(
                r"\s+", "", match.group(2)
            )

            trans4 = re.sub(
                r"\s+", "", match.group(4)
            )

            add_price(
                grade,
                "2WD",
                match.group(3),
                trans2
            )

            add_price(
                grade,
                "4WD",
                match.group(5),
                trans4
            )

    # ---------------------------------
    # ワゴンR スマイル
    # ---------------------------------

    elif method == "smile":

        text = normalize(
            soup.get_text(" ", strip=True)
        )

        price_pattern = re.compile(
            r"(?<![A-Z0-9])"
            r"(HYBRID X|HYBRID S|G)"
            r"\s+(2WD|4WD)"
            r"\s*[・/]?\s*CVT"
            r"\s*車\s*"
            r"(\d{1,3}(?:,\d{3}){2}"
            r"(?:\s+\d{1,3}(?:,\d{3}){2})*)"
            r"\s*円"
        )

        for match in price_pattern.finditer(text):

            grade = match.group(1)
            drive = match.group(2)

            prices = re.findall(
                r"\d{1,3}(?:,\d{3}){2}",
                match.group(3)
            )

            for price in prices:

                add_price(
                    grade,
                    drive,
                    price,
                    "CVT"
                )

    # =================================
    # データ不足チェック
    # =================================

    expected = {
        (grade, drive)
        for grade in grades
        for drive in ["2WD", "4WD"]
    }

    if set(groups) != expected:

        print("取得済:", sorted(groups))

        print(
            "不足:",
            sorted(expected - set(groups))
        )

        raise RuntimeError(
            "グレード構成不一致"
        )

    # =================================
    # データベース形式に変換
    # =================================

    cars = []

    for (grade, drive), prices in sorted(
        groups.items()
    ):

        price = min(prices)

        cars.append({
            "maker": "スズキ",
            "model": grade_models[grade],
            "grade": grade,
            "drive": drive,
            "transmission": transmissions[
                (grade, drive)
            ],
            "price": price,
            "price_type": "minimum_listed",
            "price_candidates": sorted(prices),
            "tax_included": True,
            "source_url": url,
            "updated_at": now,
            "status": "review_required"
        })

    return cars


# =====================================
# データベース更新
# =====================================

success = 0
failed = 0
total = 0

print("=== PRICE DATABASE ===")

for config in CONFIG:

    try:

        cars = fetch_prices(config)

        models = set(config["models"])

        # 取得成功時のみ既存車種を置換

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
                car["transmission"],
                f'{car["price"]:,}円'
            )

        total += len(cars)
        success += 1

        print(
            "取得成功:",
            len(cars),
            "件"
        )

    except Exception as error:

        failed += 1

        print(
            "取得失敗:",
            config["path"]
        )

        print("理由:", str(error))

        print("既存データを維持します")

    time.sleep(3)


if success == 0:
    raise RuntimeError("全取得処理失敗")


# =====================================
# 重複データ除外
# =====================================

unique = {}

for car in data["cars"]:

    key = (
        car.get("maker"),
        car.get("model"),
        car.get("grade"),
        car.get("drive"),
        car.get("transmission")
    )

    unique[key] = car

data["cars"] = list(unique.values())

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


# =====================================
# 未対応車種の詳細ページ調査
# =====================================

print("=== DETAIL CHECK START ===")

for model, model_path in CHECK_MODELS.items():

    url = BASE + model_path

    print("")
    print("==========")
    print("車種:", model)
    print("URL:", url)

    try:

        soup = fetch_page(url)

        items = soup.select(
            ".gradePrice__detail__price__item"
        )

        print(
            "価格要素件数:",
            len(items)
        )

        text = normalize(
            soup.get_text(" ", strip=True)
        )

        matches = list(re.finditer(
            r"\d{1,3}(?:,\d{3}){2}\s*円",
            text
        ))

        print(
            "価格候補件数:",
            len(matches)
        )

        for match in matches[:16]:

            start = max(
                0,
                match.start() - 100
            )

            end = min(
                len(text),
                match.end() + 60
            )

            print(
                "価格周辺:",
                text[start:end]
            )

        for item in items[:8]:

            print(
                "価格要素:",
                normalize(
                    item.get_text(
                        " ",
                        strip=True
                    )
                )
            )

    except Exception as error:

        print(
            "調査失敗:",
            str(error)
        )

    finally:

        time.sleep(3)

print("=== DETAIL CHECK END ===")


# =====================================
# ジムニー価格自動取得
# =====================================

print("=== JIMNY UPDATE START ===")

try:

    top_url = BASE + "jimny/"
    detail_url = BASE + "jimny/detail/"

    top_text = normalize(
        fetch_page(top_url).get_text(" ", strip=True)
    )

    detail_text = normalize(
        fetch_page(detail_url).get_text(" ", strip=True)
    )

    money = r"\d{1,3}(?:,\d{3}){2}"

    # トップページのグレードと価格候補

    top_pattern = re.compile(
        r"\bXC\s+XL\s+XG\s+"
        r"メーカー希望小売価格"
        r"\s*\(消費税10%込み\)\s*"
        r"(" + money + r")\s*円\s*[~〜]\s*"
        r"(" + money + r")\s*円\s*[~〜]\s*"
        r"(" + money + r")\s*円"
    )

    top_match = top_pattern.search(top_text)

    if not top_match:
        raise RuntimeError("グレード価格取得失敗")

    grade_prices = {
        grade: int(price.replace(",", ""))
        for grade, price in zip(
            ["XC", "XL", "XG"],
            top_match.groups()
        )
    }

    # 詳細ページの税込・税抜価格

    detail_pattern = re.compile(
        r"メーカー希望小売価格\s*"
        r"4WD\s*・\s*5MT\s*"
        r"(" + money + r")\s*円\s*"
        r"\(消費税抜き\s*"
        r"(" + money + r")\s*円\)\s*"
        r"4WD\s*・\s*4AT\s*"
        r"(" + money + r")\s*円\s*"
        r"\(消費税抜き\s*"
        r"(" + money + r")\s*円\)"
    )

    pairs = set()

    for match in detail_pattern.finditer(detail_text):

        mt, mt_net, at, at_net = [
            int(p.replace(",", ""))
            for p in match.groups()
        ]

        # 消費税10%の整合性確認

        if mt * 10 != mt_net * 11:
            raise RuntimeError("MT税込価格不一致")

        if at * 10 != at_net * 11:
            raise RuntimeError("AT税込価格不一致")

        pairs.add((mt, at))

    if len(pairs) != 3:
        raise RuntimeError("価格構成不一致")

    if len(set(grade_prices.values())) != 3:
        raise RuntimeError("グレード価格重複")

    jimny_cars = []

    for grade, base_price in grade_prices.items():

        matched = [
            pair for pair in pairs
            if min(pair) == base_price
        ]

        if len(matched) != 1:
            raise RuntimeError(
                "グレード価格照合失敗: " + grade
            )

        mt, at = matched[0]

        for transmission, price in [
            ("5MT", mt),
            ("4AT", at)
        ]:

            if not 1000000 <= price <= 5000000:
                raise RuntimeError("価格異常")

            jimny_cars.append({
                "maker": "スズキ",
                "model": "ジムニー",
                "grade": grade,
                "drive": "4WD",
                "transmission": transmission,
                "price": price,
                "price_type": "minimum_listed",
                "price_candidates": [price],
                "tax_included": True,
                "source_url": detail_url,
                "updated_at": now,
                "status": "review_required"
            })

    if len(jimny_cars) != 6:
        raise RuntimeError("ジムニーデータ不足")

    # 取得成功時のみ置き換え

    new_data = dict(data)

    new_data["cars"] = [
        car for car in data["cars"]
        if not (
            car.get("maker") == "スズキ"
            and car.get("model") == "ジムニー"
        )
    ]

    new_data["cars"].extend(jimny_cars)
    new_data["updated_at"] = now

    temp = preview.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            new_data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(preview)

    data = new_data

    for car in jimny_cars:

        print(
            car["model"],
            car["grade"],
            car["drive"],
            car["transmission"],
            f'{car["price"]:,}円'
        )

    print("ジムニー追加成功: 6件")
    print("DB登録総件数:", len(data["cars"]))

except Exception as error:

    print("ジムニー取得失敗:", str(error))
    print("既存データを維持します")

print("=== JIMNY UPDATE END ===")



# =====================================
# JavaScript・価格データ構造調査
# =====================================

from urllib.parse import urljoin, urlparse

print("=== ADVANCED PRICE CHECK START ===")

ADVANCED_MODELS = {
    "アルト": "alto/detail/",
    "ラパン": "lapin/detail/",
    "エブリイワゴン": "everywagon/detail/"
}

money_pattern = re.compile(
    r"(?<!\d)"
    r"(?:\d{1,3}(?:,\d{3}){2}|[1-4]\d{6})"
    r"(?!\d)"
)

keyword_pattern = re.compile(
    r"price|grade|vehicle|carData|"
    r"modelData|json|税込|希望小売価格",
    re.I
)

checked_scripts = set()

for model, model_path in ADVANCED_MODELS.items():

    url = BASE + model_path

    print("")
    print("================================")
    print("調査車種:", model)
    print("URL:", url)
    print("================================")

    try:

        soup = fetch_page(url)

        # HTML内部の価格候補を調査

        html = normalize(str(soup))

        matches = list(
            money_pattern.finditer(html)
        )

        print(
            "HTML内価格候補件数:",
            len(matches)
        )

        for match in matches[:12]:

            start = max(
                0, match.start() - 100
            )

            end = min(
                len(html), match.end() + 100
            )

            print(
                "HTML価格周辺:",
                html[start:end]
            )

        # 価格関連のHTML要素を調査

        elements = soup.find_all(
            attrs={
                "class": re.compile(
                    r"price|grade", re.I
                )
            }
        )

        print(
            "価格関連要素件数:",
            len(elements)
        )

        for element in elements[:15]:

            print(
                "価格要素:",
                str(element)[:700]
            )

        # JavaScriptファイルの調査

        script_urls = []

        for script in soup.find_all("script"):

            src = script.get("src")

            if not src:

                content = script.get_text()

                if keyword_pattern.search(content):

                    print(
                        "埋込Script:",
                        normalize(content)[:500]
                    )

                continue

            script_url = urljoin(url, src)

            parsed = urlparse(script_url)

            if (
                parsed.scheme != "https"
                or parsed.netloc
                != "www.suzuki.co.jp"
            ):
                continue

            if script_url not in script_urls:

                script_urls.append(script_url)

        print(
            "公式JSファイル件数:",
            len(script_urls)
        )

        for script_url in script_urls:

            print("JS URL:", script_url)

        # 車種固有・価格関連JSを優先

        model_key = model_path.split("/")[0]

        candidates = [
            u for u in script_urls
            if re.search(
                model_key
                + r"|price|grade|data|detail",
                urlparse(u).path,
                re.I
            )
        ]

        candidates = candidates[:8]

        print(
            "JS調査対象件数:",
            len(candidates)
        )

        for script_url in candidates:

            if script_url in checked_scripts:
                continue

            try:

                if not robots.can_fetch(
                    AGENT, script_url
                ):

                    print("JS取得制限あり")
                    continue

                checked_scripts.add(script_url)

                js_response = session.get(
                    script_url,
                    timeout=15,
                    allow_redirects=False
                )

                if js_response.status_code != 200:

                    print(
                        "JS HTTP:",
                        js_response.status_code
                    )

                    continue

                js_text = normalize(
                    js_response.text
                )

                print("")
                print("JS調査:", script_url)

                js_matches = list(
                    money_pattern.finditer(
                        js_text
                    )
                )

                print(
                    "JS内価格候補件数:",
                    len(js_matches)
                )

                for match in js_matches[:8]:

                    start = max(
                        0, match.start() - 100
                    )

                    end = min(
                        len(js_text),
                        match.end() + 100
                    )

                    print(
                        "JS価格周辺:",
                        js_text[start:end]
                    )

                # JSON・CSV等の参照先調査

                references = re.findall(
                    r"""["']([^"']{1,250}\.(?:json|csv)(?:\?[^"']*)?)["']""",
                    js_text,
                    flags=re.I
                )

                for reference in list(
                    dict.fromkeys(references)
                )[:15]:

                    print(
                        "データ参照先:",
                        reference
                    )

            except Exception as error:

                print(
                    "JS調査失敗:",
                    str(error)
                )

            finally:

                time.sleep(3)

    except Exception as error:

        print(
            "詳細調査失敗:",
            str(error)
        )

    finally:

        time.sleep(3)

print("=== ADVANCED PRICE CHECK END ===")


# =====================================
# Playwright アルト価格取得テスト
# =====================================

from playwright.sync_api import sync_playwright

print("=== PLAYWRIGHT ALTO START ===")

try:

    url = BASE + "alto/detail/"

    if not robots.can_fetch(AGENT, url):
        raise RuntimeError("自動取得制限あり")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        try:

            context = browser.new_context(
                locale="ja-JP",
                user_agent=AGENT
            )

            def check_request(route):

                target = urlparse(route.request.url)

                if (
                    target.scheme != "https"
                    or target.netloc != "www.suzuki.co.jp"
                    or not robots.can_fetch(
                        AGENT, route.request.url
                    )
                ):
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", check_request)

            page = context.new_page()

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response is None or not response.ok:
                raise RuntimeError("ページ取得失敗")

            print("ページタイトル:", page.title())
            print("ページURL:", page.url)

            # JavaScriptによる価格表示を待機

            try:

                page.wait_for_function(
                    """() => Array.from(
                        document.querySelectorAll(
                            '[data-prices]'
                        )
                    ).some(
                        e => /[0-9,]+\\s*円/.test(
                            e.innerText
                        )
                    )""",
                    timeout=20000
                )

            except Exception:

                print("価格表示待機タイムアウト")

            # JavaScript実行後のHTML取得

            soup = BeautifulSoup(
                page.content(),
                "html.parser"
            )

            text = normalize(
                page.locator("body").inner_text()
            )

            # 価格表示要素の確認

            elements = soup.select(
                "[data-prices]"
            )

            print(
                "価格表示要素件数:",
                len(elements)
            )

            for i, element in enumerate(elements):

                content = normalize(
                    element.get_text(
                        " ", strip=True
                    )
                )

                print("価格要素番号:", i + 1)
                print("価格内容:", content)

                parent = element

                for level in range(4):

                    if parent is None:
                        break

                    print("LEVEL:", level)

                    print(
                        "周辺情報:",
                        normalize(
                            parent.get_text(
                                " ", strip=True
                            )
                        )[:600]
                    )

                    parent = parent.parent

            # 車両価格候補の確認

            matches = list(re.finditer(
                r"\d{1,3}(?:,\d{3}){2}\s*円",
                text
            ))

            print(
                "ブラウザ価格候補件数:",
                len(matches)
            )

            for match in matches[:30]:

                start = max(
                    0, match.start() - 100
                )

                end = min(
                    len(text),
                    match.end() + 80
                )

                print(
                    "価格周辺:",
                    text[start:end]
                )

        finally:

            browser.close()

except Exception as error:

    print(
        "Playwright取得失敗:",
        str(error)
    )

print("=== PLAYWRIGHT ALTO END ===")
