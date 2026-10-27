
import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.soccerstats.com/halftime.asp"
LEAGUES = {
    "england": "England",
}

OUTPUT_DIR = Path("output")
DEBUG_DIR = Path("debug")
CSV_FILE = OUTPUT_DIR / "soccerstats_second_half.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30
REQUEST_DELAY = 3

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


def clean_text(value):
    """Normalize whitespace in text."""
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_header(value):
    """Normalize table header text for matching."""
    value = clean_text(value).lower()
    value = value.replace("≥", ">=")
    value = value.replace("％", "%")
    return value


def save_diagnostics(slug, html, text):
    """Save the downloaded page for troubleshooting."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    (DEBUG_DIR / f"{slug}.html").write_text(
        html, encoding="utf-8"
    )
    (DEBUG_DIR / f"{slug}.txt").write_text(
        text, encoding="utf-8"
    )


def get_page(url):
    """Download a page and return HTML."""
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Downloaded bytes: {len(response.content)}")

    response.raise_for_status()

    # SoccerSTATS may return a block page or a challenge instead
    # of the requested statistics table.
    if not response.text.strip():
        raise RuntimeError("The website returned an empty response.")

    return response.text


def find_statistics_table(soup):
    """
    Find a table containing team second-half goal statistics.

    The website may change its HTML structure. If the expected
    columns are not present, the caller saves diagnostics.
    """
    required_columns = {"teams", "gp", "avg", "0.5+", "1.5+"}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Check each row because table headings may occupy
        # a separate row or be split across multiple rows.
        for header_row in rows[:5]:
            cells = header_row.find_all(["th", "td"])
            headers = [
                normalize_header(cell.get_text(" ", strip=True))
                for cell in cells
            ]

            joined = " ".join(headers)

            has_team_column = (
                "teams" in joined
                or "team" in joined
            )

            has_gp = any(
                h == "gp" or h.startswith("gp ")
                for h in headers
            )
            has_avg = any(
                h == "avg" or h.startswith("avg ")
                for h in headers
            )
            has_half_goal = any(
                "0.5+" in h or "0.5 +" in h
                for h in headers
            )
            has_one_goal = any(
                "1.5+" in h or "1.5 +" in h
                for h in headers
            )

            if (
                has_team_column
                and has_gp
                and has_avg
                and has_half_goal
                and has_one_goal
            ):
                return table

    # Fallback: inspect all tables for the characteristic
    # combination of column names.
    for table in soup.find_all("table"):
        table_text = normalize_header(
            table.get_text(" ", strip=True)
        )

        if (
            "teams" in table_text
            and "avg" in table_text
            and "0.5+" in table_text
            and "1.5+" in table_text
        ):
            return table

    return None


def extract_column_indexes(table):
    """Map known column labels to their positions."""
    rows = table.find_all("tr")

    for header_row in rows[:5]:
        cells = header_row.find_all(["th", "td"])
        headers = [
            normalize_header(cell.get_text(" ", strip=True))
            for cell in cells
        ]

        indexes = {}

        for index, header in enumerate(headers):
            if header in ("team", "teams") or header.startswith("teams "):
                indexes["team"] = index
            elif header == "gp" or header.startswith("gp "):
                indexes["GP"] = index
            elif header == "avg" or header.startswith("avg "):
                indexes["Avg"] = index
            elif "0.5+" in header or "0.5 +" in header:
                indexes["0.5+"] = index
            elif "1.5+" in header or "1.5 +" in header:
                indexes["1.5+"] = index
            elif "2.5+" in header or "2.5 +" in header:
                indexes["2.5+"] = index
            elif "3.5+" in header or "3.5 +" in header:
                indexes["3.5+"] = index

        if {"team", "GP", "Avg", "0.5+", "1.5+"}.issubset(indexes):
            return indexes, rows.index(header_row)

    return None, None


def extract_rows(table, league_slug, league_name, source_url):
    """Extract team records from the statistics table."""
    result = extract_column_indexes(table)

    if result[0] is None:
        return []

    indexes, header_row_index = result
    rows = table.find_all("tr")
    collected_at = datetime.now(timezone.utc).isoformat()
    records = []

    for row in rows[header_row_index + 1:]:
        cells = row.find_all(["td", "th"])

        if not cells:
            continue

        # Skip rows that do not contain all mandatory columns.
        if max(indexes.values()) >= len(cells):
            continue

        values = {
            key: clean_text(cells[index].get_text(" ", strip=True))
            for key, index in indexes.items()
        }

        team = values.get("team", "")

        if not team:
            continue

        # Exclude header-like rows and footnotes.
        if normalize_header(team) in {"team", "teams"}:
            continue

        # GP should contain a number for a valid team row.
        if not re.search(r"\d", values.get("GP", "")):
            continue

        record = {
            "league_slug": league_slug,
            "league_name": league_name,
            "team": team,
            "GP": values.get("GP", ""),
            "Avg": values.get("Avg", ""),
            "0.5+": values.get("0.5+", ""),
            "1.5+": values.get("1.5+", ""),
            "2.5+": values.get("2.5+", ""),
            "3.5+": values.get("3.5+", ""),
            "source_url": source_url,
            "collected_at_utc": collected_at,
        }

        records.append(record)

    return records


def write_csv(records):
    """Write records to CSV using UTF-8 with BOM for spreadsheet compatibility."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
        writer.writerows(records)

    print(f"\nCSV saved: {CSV_FILE}")
    print(f"Total records: {len(records)}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_records = []
    errors = []

    for slug, league_name in LEAGUES.items():
        url = BASE_URL

        print("=" * 60)
        print(f"League: {league_name}")
        print(f"URL: {url}")

        try:
            html = get_page(url)
            soup = BeautifulSoup(html, "html.parser")

            table = find_statistics_table(soup)

            if table is None:
                page_text = soup.get_text("\n", strip=True)
                save_diagnostics(slug, html, page_text)

                message = (
                    f"{league_name}: statistics table not found. "
                    f"Diagnostics saved in {DEBUG_DIR}/"
                )
                print(f"ERROR: {message}")
                errors.append(message)
                continue

            records = extract_rows(
                table=table,
                league_slug=slug,
                league_name=league_name,
                source_url=url,
            )

            if not records:
                page_text = soup.get_text("\n", strip=True)
                save_diagnostics(slug, html, page_text)

                message = (
                    f"{league_name}: table found, but no team "
                    "records could be extracted."
                )
                print(f"ERROR: {message}")
                errors.append(message)
                continue

            all_records.extend(records)

            print(f"Teams collected: {len(records)}")
            for record in records[:5]:
                print(
                    f"  {record['team']} | "
                    f"GP={record['GP']} | "
                    f"Avg={record['Avg']} | "
                    f"0.5+={record['0.5+']} | "
                    f"1.5+={record['1.5+']}"
                )

        except Exception as exc:
            message = f"{league_name}: {type(exc).__name__}: {exc}"
            print(f"ERROR: {message}")
            errors.append(message)

        time.sleep(REQUEST_DELAY)

    if all_records:
        write_csv(all_records)

    if errors:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / "errors.txt").write_text(
            "\n".join(errors),
            encoding="utf-8",
        )

        print("\nCollection completed with errors:")
        for error in errors:
            print(f"- {error}")

        return 1

    if not all_records:
        print("ERROR: no records collected.")
        return 1

    print("\nCollection completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
