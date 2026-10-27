
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SoccerSTATS collector
Table: Match total goals stats in the SECOND HALF

Initial test: England only.
Output: output/soccerstats_second_half.csv
Diagnostics: debug/
"""

import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.soccerstats.com/halftime.asp"

# Початковий тест однієї ліги.
# Інші ліги додаватимемо після перевірки результату.
LEAGUES = {
    "england": "England",
}

OUTPUT_DIR = Path("output")
DEBUG_DIR = Path("debug")
CSV_FILE = OUTPUT_DIR / "soccerstats_second_half.csv"

REQUEST_DELAY = 3
TIMEOUT = 30

CSV_COLUMNS = [
    "league_slug",
    "league_name",
    "team",
    "GP",
    "Avg",
    "0.5+",
    "1.5+",
    "2.5+",
    "3.5+",
    "source_url",
    "collected_at_utc",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_header(value):
    value = clean(value).lower()
    value = value.replace(" ", "").replace("%", "")
    return value.replace("–", "-").replace("—", "-")


def parse_number(value):
    """Повертає число або None, якщо значення відсутнє."""
    value = clean(value).replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def row_cells(row):
    """Читає лише безпосередні клітинки рядка."""
    return [
        clean(cell.get_text(" ", strip=True))
        for cell in row.find_all(
            ["th", "td"],
            recursive=False,
        )
    ]


def find_statistics_table(soup):
    """
    Знаходить таблицю за заголовками:
    Teams (Second-Half), GP, Avg, 0.5+, 1.5+.
    """

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        for row_index, row in enumerate(rows):
            cells = row_cells(row)

            if not cells:
                continue

            headers = [
                normalize_header(cell)
                for cell in cells
            ]

            team_column = any(
                "team" in header
                and (
                    "second-half" in header
                    or "secondhalf" in header
                )
                for header in headers
            )

            required = (
                team_column
                and "gp" in headers
                and "avg" in headers
                and any(
                    h in {"0.5", "0.5+"}
                    for h in headers
                )
                and any(
                    h in {"1.5", "1.5+"}
                    for h in headers
                )
            )

            if required:
                return table, rows, row_index, headers

    return None, [], -1, []


def save_debug(slug, html, message):
    """Зберігає HTML сторінки та опис проблеми."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    (DEBUG_DIR / f"{slug}.html").write_text(
        html,
        encoding="utf-8",
    )

    (DEBUG_DIR / f"{slug}.txt").write_text(
        message + "\n",
        encoding="utf-8",
    )


def fetch_league(session, slug, league_name):
    url = f"{BASE_URL}?league={slug}"

    print(f"\n[INFO] Ліга: {league_name}")
    print(f"[URL] {url}")

    response = session.get(
        url,
        timeout=TIMEOUT,
    )

    print(f"[HTTP] {response.status_code}")
    print(
        "[CONTENT-TYPE] "
        + response.headers.get("content-type", "unknown")
    )
    print(f"[HTML-BYTES] {len(response.content)}")

    response.raise_for_status()

    if len(response.content) < 1000:
        save_debug(
            slug,
            response.text,
            "Відповідь надто коротка: можливо, блокування або помилка сайту.",
        )
        raise RuntimeError("Отримано надто коротку HTML-сторінку.")

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    table, rows, header_index, headers = (
        find_statistics_table(soup)
    )

    if table is None:
        save_debug(
            slug,
            response.text,
            "Не знайдено очікувану таблицю статистики другого тайму.",
        )
        raise RuntimeError(
            "Таблицю не знайдено. Перевір debug/"
        )

    def index_of(*names):
        for name in names:
            if name in headers:
                return headers.index(name)
        return None

    team_index = next(
        i
        for i, header in enumerate(headers)
        if "team" in header
        and (
            "second-half" in header
            or "secondhalf" in header
        )
    )

    indexes = {
        "GP": index_of("gp"),
        "Avg": index_of("avg"),
        "0.5+": index_of("0.5+", "0.5"),
        "1.5+": index_of("1.5+", "1.5"),
        "2.5+": index_of("2.5+", "2.5"),
        "3.5+": index_of("3.5+", "3.5"),
    }

    records = []
    collected_at = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    for row in rows[header_index + 1:]:
        cells = row_cells(row)

        if not cells or team_index >= len(cells):
            continue

        team = clean(cells[team_index])

        if not team:
            continue

        gp_index = indexes["GP"]
        avg_index = indexes["Avg"]

        if (
            gp_index is None
            or avg_index is None
            or max(gp_index, avg_index) >= len(cells)
        ):
            continue

        gp = parse_number(cells[gp_index])
        avg = parse_number(cells[avg_index])

        # Пропускаємо заголовки, підсумки та невалідні рядки.
        if gp is None or avg is None:
            continue

        record = {
            "league_slug": slug,
            "league_name": league_name,
            "team": team,
            "GP": int(gp),
            "Avg": avg,
            "source_url": url,
            "collected_at_utc": collected_at,
        }

        for metric in ("0.5+", "1.5+", "2.5+", "3.5+"):
            idx = indexes[metric]

            if idx is not None and idx < len(cells):
                record[metric] = parse_number(cells[idx])
            else:
                record[metric] = None

        records.append(record)

    if not records:
        save_debug(
            slug,
            response.text,
            f"Таблицю знайдено, але команд не розпізнано. Заголовки: {headers}",
        )
        raise RuntimeError(
            "У таблиці не розпізнано жодної команди."
        )

    print(f"[OK] Команд зібрано: {len(records)}")

    for record in records[:5]:
        print(
            f"{record['team']} | "
            f"GP={record['GP']} | "
            f"Avg={record['Avg']} | "
            f"0.5+={record['0.5+']} | "
            f"1.5+={record['1.5+']}"
        )

    return records


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    all_records = []
    errors = []

    for slug, league_name in LEAGUES.items():
        try:
            records = fetch_league(
                session,
                slug,
                league_name,
            )
            all_records.extend(records)

        except Exception as exc:
            message = (
                f"{league_name} ({slug}): "
                f"{type(exc).__name__}: {exc}"
            )
            errors.append(message)
            print(f"[ERROR] {message}", file=sys.stderr)

        time.sleep(REQUEST_DELAY)

    if all_records:
        with CSV_FILE.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=CSV_COLUMNS,
            )
            writer.writeheader()
            writer.writerows(all_records)

        print(f"\n[DONE] Рядків у CSV: {len(all_records)}")
        print(f"[CSV] {CSV_FILE}")

    else:
        print("\n[FAIL] Дані не зібрано. CSV не створено.")

    if errors:
        (DEBUG_DIR / "errors.txt").write_text(
            "\n".join(errors) + "\n",
            encoding="utf-8",
        )
        print("[WARN] Деталі помилок збережено в debug/errors.txt")
        return 1

    return 0 if all_records else 1


if __name__ == "__main__":
    raise SystemExit(main())
