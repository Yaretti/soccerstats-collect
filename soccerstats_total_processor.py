
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SOCCERSTATS TOTAL PROCESSOR

Обробка вручну експортованих CSV-файлів.
Дані: Match total goals stats.

Вихід:
output/team_total.csv
"""

import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DEBUG_DIR = Path("debug")

OUTPUT_FILE = OUTPUT_DIR / "team_total.csv"

# Очікувана структура вихідної бази
OUTPUT_COLUMNS = [
    "league",
    "season",
    "team",
    "GP",
    "Avg",
    "0.5+",
    "1.5+",
    "2.5+",
    "3.5+",
    "source_file",
    "collected_at_utc",
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    value = clean(value).lower()
    value = value.replace("%", "")
    value = value.replace(" ", "")
    return value.replace("–", "-")


def parse_number(value):
    value = clean(value).replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


def find_column(headers, candidates):
    normalized = [normalize(h) for h in headers]

    for candidate in candidates:
        candidate = normalize(candidate)

        for index, header in enumerate(normalized):
            if header == candidate:
                return index

    return None


def detect_columns(headers):

    columns = {
        "team": find_column(
            headers,
            ["Team", "Teams", "Club"]
        ),
        "GP": find_column(
            headers,
            ["GP", "Played", "Games"]
        ),
        "Avg": find_column(
            headers,
            ["Avg", "Average"]
        ),
        "0.5+": find_column(
            headers,
            ["0.5+", "Over 0.5", "Over 0.5+"]
        ),
        "1.5+": find_column(
            headers,
            ["1.5+", "Over 1.5", "Over 1.5+"]
        ),
        "2.5+": find_column(
            headers,
            ["2.5+", "Over 2.5", "Over 2.5+"]
        ),
        "3.5+": find_column(
            headers,
            ["3.5+", "Over 3.5", "Over 3.5+"]
        ),
    }

    missing = [
        name for name, index in columns.items()
        if index is None
    ]

    if missing:
        raise ValueError(
            "Не знайдено стовпці: " + ", ".join(missing)
        )

    return columns


def read_csv_file(path):

    encodings = ["utf-8-sig", "utf-8", "cp1252"]

    for encoding in encodings:
        try:
            with path.open(
                "r",
                encoding=encoding,
                newline=""
            ) as file:

                sample = file.read(4096)
                file.seek(0)

                try:
                    dialect = csv.Sniffer().sniff(
                        sample,
                        delimiters=",;\t"
                    )
                except csv.Error:
                    dialect = csv.excel

                reader = csv.reader(file, dialect)
                rows = list(reader)

                return rows

        except UnicodeDecodeError:
            continue

    raise ValueError(
        f"Не вдалося прочитати файл: {path.name}"
    )


def process_file(path):

    print(f"\n[FILE] {path.name}")

    rows = read_csv_file(path)

    if len(rows) < 2:
        raise ValueError("Файл не містить даних.")

    headers = rows[0]
    columns = detect_columns(headers)

    # Метадані задаються в назві файлу:
    # england_2026-27.csv
    parts = path.stem.rsplit("_", 1)

    if len(parts) == 2:
        league = parts[0].replace("-", " ").title()
        season = parts[1].replace("-", "/")
    else:
        league = "UNKNOWN"
        season = "UNKNOWN"

    collected_at = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    records = []

    for row_number, row in enumerate(rows[1:], start=2):

        try:
            team_index = columns["team"]

            if team_index >= len(row):
                continue

            team = clean(row[team_index])

            if not team:
                continue

            record = {
                "league": league,
                "season": season,
                "team": team,
                "GP": None,
                "Avg": None,
                "0.5+": None,
                "1.5+": None,
                "2.5+": None,
                "3.5+": None,
                "source_file": path.name,
                "collected_at_utc": collected_at,
            }

            for metric in [
                "GP", "Avg", "0.5+", "1.5+", "2.5+", "3.5+"
            ]:
                index = columns[metric]

                if index < len(row):
                    record[metric] = parse_number(row[index])

            if record["GP"] is None or record["GP"] <= 0:
                continue

            if record["Avg"] is None:
                continue

            records.append(record)

        except Exception as exc:
            print(
                f"[WARN] Рядок {row_number}: {exc}"
            )

    print(f"[OK] Команд: {len(records)}")

    return records


def save_records(records):

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Об'єднання з уже наявною базою.
    existing = {}

    if OUTPUT_FILE.exists():

        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            for row in csv.DictReader(file):
                key = (
                    row["league"],
                    row["season"],
                    row["team"]
                )
                existing[key] = row

    # Нові дані замінюють старі записи тієї самої команди,
    # ліги та сезону.
    for record in records:

        key = (
            record["league"],
            record["season"],
            record["team"]
        )

        existing[key] = record

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_COLUMNS
        )

        writer.writeheader()
        writer.writerows(existing.values())

    print(f"\n[DONE] Записів у базі: {len(existing)}")
    print(f"[CSV] {OUTPUT_FILE}")


def main():

    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    DEBUG_DIR.mkdir(exist_ok=True)

    files = list(INPUT_DIR.glob("*.csv"))

    if not files:
        print("[ERROR] У папці input немає CSV-файлів.")
        return 1

    all_records = []
    errors = []

    for path in sorted(files):

        try:
            all_records.extend(
                process_file(path)
            )

        except Exception as exc:

            message = f"{path.name}: {exc}"
            errors.append(message)

            print(f"[ERROR] {message}")

    if all_records:
        save_records(all_records)

    if errors:

        error_file = DEBUG_DIR / "errors.txt"

        error_file.write_text(
            "\n".join(errors),
            encoding="utf-8"
        )

        print(f"\n[WARN] Помилки: {error_file}")
        return 1

    if not all_records:
        print("[ERROR] Жодного запису не оброблено.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
