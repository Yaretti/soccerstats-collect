#!/usr/bin/env python3
"""Збір голів 2-го тайму з SoccerSTATS (halftime.asp) -> soccerstats_stats.csv
Запуск: python3 soccerstats_collect.py   (pip install requests beautifulsoup4)
Можна перервати й запустити знову: вже зібрані ліги пропускаються.
УВАГА: код написано без тесту на живому сайті; спершу пробний запуск: python3 soccerstats_collect.py qatar
"""
import csv, os, re, sys, time
import requests
from bs4 import BeautifulSoup

BASE = 'https://www.soccerstats.com/'
UA = {'User-Agent': 'Mozilla/5.0 (GreenlineGoal league rating, low-rate)'}
DELAY = 4  # секунд між запитами, не зменшувати
OUT = 'soccerstats_stats.csv'
FIELDS = ['slug', 'league_name', 'season_label', 'matches', 'p05', 'p15', 'p25', 'avg_goals_2h', 'url']

def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    time.sleep(DELAY)
    return r.text

def list_leagues():
    soup = BeautifulSoup(get(BASE + 'leagues.asp'), 'html.parser')
    out = {}
    for a in soup.find_all('a', href=True):
        m = re.search(r'latest\.asp\?league=([a-z0-9]+)$', a['href'])
        if m and a.get_text(strip=True):
            out.setdefault(m.group(1), a.get_text(' ', strip=True))
    return out

def table_after(soup, pattern):
    el = soup.find(string=re.compile(pattern))
    return el.find_next('table') if el else None

def parse_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    # сезони з випадаючого списку: label -> slug
    seasons = {}
    for a in soup.find_all('a', href=True):
        m = re.search(r'latest\.asp\?league=([a-z0-9_]+)', a['href'])
        t = a.get_text(strip=True)
        if m and re.fullmatch(r'20\d\d(/\d{2,4})?', t):
            seasons[t] = m.group(1)
    # таблиця 2Т (46-90) -> GP та GF
    t = table_after(soup, r'Second Half table \(46-90 min\.\)\s*$')
    gp = gf = 0
    if t:
        for tr in t.find_all('tr'):
            c = [x.get_text(' ', strip=True) for x in tr.find_all(['td', 'th'])]
            if len(c) >= 8 and c[-8].isdigit() and c[-4].isdigit():
                gp += int(c[-8]); gf += int(c[-4])
    matches = gp // 2 if gp % 2 == 0 else None
    # League average у блоці SECOND HALF (загальний, не home/away)
    tt = table_after(soup, r'^\s*Match (total )?goals stats in the SECOND HALF\s*$')
    pct = None
    if tt:
        for tr in tt.find_all('tr'):
            c = [x.get_text(' ', strip=True) for x in tr.find_all(['td', 'th'])]
            if any(x == 'League average' for x in c):
                p = [float(x.rstrip('%')) for x in c if re.fullmatch(r'\d+(\.\d+)?%', x)]
                if len(p) >= 3: pct = p[:3]
                break
    return seasons, matches, gf, pct

def main():
    only = sys.argv[1:]  # необов'язково: список slug для проби
    leagues = {s: s for s in only} if only else list_leagues()
    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            done = {(r['slug'], r['season_label']) for r in csv.DictReader(f)}
    new = not os.path.exists(OUT)
    with open(OUT, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, FIELDS)
        if new: w.writeheader()
        for base, name in leagues.items():
            try:
                url0 = f'{BASE}halftime.asp?league={base}'
                seasons, *_ = parse_page(get(url0))
                targets = {}
                for lab, slug in seasons.items():
                    y = int(lab[:4])
                    if y in (2025, 2026): targets[lab] = slug
                if not targets:
                    print('нема сезонів 2025/2026:', base); continue
                for lab, slug in targets.items():
                    if (slug, lab) in done: continue
                    url = f'{BASE}halftime.asp?league={slug}'
                    _, matches, gf, pct = parse_page(get(url))
                    if not matches or not pct:
                        print('НЕМАЄ ДАНИХ 2Т:', slug, lab); continue
                    w.writerow(dict(slug=slug, league_name=name, season_label=lab, matches=matches,
                                    p05=pct[0], p15=pct[1], p25=pct[2],
                                    avg_goals_2h=round(gf / matches, 2), url=url))
                    f.flush(); print('ok', slug, lab, matches)
            except Exception as e:
                print('ПОМИЛКА', base, e)

if __name__ == '__main__':
    main()
