#!/usr/bin/env python3
"""
Fetches current World Cup fixture data from API-Football and rewrites the
REAL[] / REAL16[] result blocks in index.html to match.

Requires an environment variable API_FOOTBALL_KEY (set as a GitHub Actions
secret — see .github/workflows/update-scores.yml).

IMPORTANT: this pulls from a REAL, live sports data API. If you're using this
repo to track a specific narrative (rather than the actual real-world 2026
World Cup as it unfolds), double-check the fixture IDs/league ID below match
what you expect before relying on this in production.
"""

import os
import re
import sys
import requests

API_KEY = os.environ.get("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# FIFA World Cup competition ID in API-Football's system.
# NOTE: verify this against your API-Football dashboard — league IDs can
# differ by data provider, and this should be double-checked with a real key
# before relying on it (see Football (search "api-football league id world cup")
LEAGUE_ID = 1
SEASON = 2026

# ---- team name -> our 3-letter code, matching the TEAMS[] array in index.html ----
# API-Football's own naming may differ slightly (e.g. "Ivory Coast" vs "Côte d'Ivoire").
# Add aliases here as you discover mismatches from real API responses.
NAME_TO_CODE = {
    "Brazil": "BRA", "Japan": "JPN", "Ivory Coast": "CIV", "Côte d'Ivoire": "CIV",
    "Norway": "NOR", "Mexico": "MEX", "Ecuador": "ECU", "England": "ENG",
    "DR Congo": "COD", "Congo DR": "COD", "DRCongo": "COD",
    "Argentina": "ARG", "Cape Verde": "CPV", "Australia": "AUS", "Egypt": "EGY",
    "Switzerland": "SUI", "Algeria": "ALG", "Colombia": "COL", "Ghana": "GHA",
    "Senegal": "SEN", "Belgium": "BEL", "Bosnia and Herzegovina": "BIH", "Bosnia & Herz.": "BIH",
    "USA": "USA", "United States": "USA", "Austria": "AUT", "Spain": "ESP",
    "Croatia": "CRO", "Portugal": "POR", "Morocco": "MAR", "Netherlands": "NED",
    "Canada": "CAN", "South Africa": "RSA", "Sweden": "SWE", "France": "FRA",
    "Paraguay": "PAR", "Germany": "GER",
}

# leaf index (matches TEAMS[] order in index.html) for each code
CODE_TO_IDX = {
    "BRA":0,"JPN":1,"CIV":2,"NOR":3,"MEX":4,"ECU":5,"ENG":6,"COD":7,
    "ARG":8,"CPV":9,"AUS":10,"EGY":11,"SUI":12,"ALG":13,"COL":14,"GHA":15,
    "SEN":16,"BEL":17,"BIH":18,"USA":19,"AUT":20,"ESP":21,"CRO":22,"POR":23,
    "MAR":24,"NED":25,"CAN":26,"RSA":27,"SWE":28,"FRA":29,"PAR":30,"GER":31,
}

# fixed R32 pairs (leaf idx a,b), in the same order as REAL[] / FIXTURES{} in index.html
R32_PAIRS = [
    (0,1),(2,3),(4,5),(6,7),(8,9),(10,11),(12,13),(14,15),
    (16,17),(18,19),(20,21),(22,23),(24,25),(26,27),(28,29),(30,31),
]

# fixed R16 pairs (leaf idx a,b — both R32 winners), matching REAL16[] / FIXTURES16{} order
R16_PAIRS = [
    (0,3),(4,6),(8,11),(12,14),(17,19),(21,23),(24,26),(29,30),
]


def fetch_fixtures():
    r = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": LEAGUE_ID, "season": SEASON},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("response", [])


def idx_for_name(name):
    code = NAME_TO_CODE.get(name)
    return CODE_TO_IDX.get(code) if code else None


def build_entry(pair, fixtures_by_pair):
    """Build one REAL/REAL16-style dict entry for a given (a,b) leaf-index pair.
    Returns None if no fixture data was found — the caller must leave that
    entry completely untouched in that case, never overwrite it with a guess."""
    a, b = pair
    fx = fixtures_by_pair.get(frozenset(pair))
    if fx is None:
        return None

    status = fx["fixture"]["status"]["short"]
    home_idx = idx_for_name(fx["teams"]["home"]["name"])
    goals_home = fx["goals"]["home"] or 0
    goals_away = fx["goals"]["away"] or 0
    # normalise so hs/as always correspond to leaf a / leaf b, regardless of API home/away order
    if home_idx == a:
        hs, as_ = goals_home, goals_away
    else:
        hs, as_ = goals_away, goals_home

    if status in ("1H", "2H", "ET", "P", "LIVE", "HT"):
        minute = fx["fixture"]["status"].get("elapsed")
        minute_text = f"{minute}'" if minute else "LIVE"
        return {"a": a, "b": b, "winner": None, "live": {"hs": hs, "as_": as_, "minute": minute_text}}

    if status in ("FT", "AET", "PEN"):
        note = None
        winner = a if hs > as_ else b if as_ > hs else None
        if status == "PEN":
            pen = fx.get("score", {}).get("penalty", {})
            ph, pa = pen.get("home"), pen.get("away")
            if ph is not None and pa is not None:
                home_pen, away_pen = (ph, pa) if home_idx == a else (pa, ph)
                winner = a if home_pen > away_pen else b
                winner_name = fx["teams"]["home" if (home_pen > away_pen) == (home_idx == a) else "away"]["name"]
                note = f"{winner_name} win {max(home_pen,away_pen)}-{min(home_pen,away_pen)} on penalties"
        entry = {"a": a, "b": b, "hs": hs, "as_": as_, "winner": winner}
        if note:
            entry["note"] = note
        return entry

    if status == "NS":
        return None  # genuinely not started yet — nothing new to report, leave existing entry alone

    # any other/unrecognized status: be conservative and skip rather than guess
    return None


def js_value(v):
    if v is None:
        return "null"
    if isinstance(v, str):
        if "'" in v and '"' not in v:
            return '"' + v + '"'
        return "'" + v.replace("'", "\\'") + "'"
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            key = "as" if k == "as_" else k
            parts.append(f"{key}:{js_value(val)}")
        return "{" + ",".join(parts) + "}"
    return str(v)


def render_row(e):
    return "{" + ",".join(f"{('as' if k=='as_' else k)}:{js_value(v)}" for k, v in e.items()) + "}"


def find_entry_span(html, a, b):
    """Locate the exact {a:X,b:Y...} object literal for this pair, handling
    nested braces (e.g. a live:{...} sub-object) via brace counting rather
    than a naive regex, so we only ever replace that one object — nothing
    else on the line (trailing comma, comments) is touched."""
    prefix = f"{{a:{a},b:{b}"
    start = html.find(prefix)
    if start == -1:
        return None
    depth = 0
    i = start
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        i += 1
    return None


def update_entry_in_html(html, pair, entry):
    a, b = pair
    span = find_entry_span(html, a, b)
    if span is None:
        print(f"WARNING: could not locate existing entry for a={a},b={b} in index.html — leaving untouched.")
        return html, False
    start, end = span
    return html[:start] + render_row(entry) + html[end:], True


def main():
    if not API_KEY:
        print("ERROR: API_FOOTBALL_KEY environment variable not set.")
        sys.exit(1)
    fixtures = fetch_fixtures()
    fixtures_by_pair = {}
    for fx in fixtures:
        hi = idx_for_name(fx["teams"]["home"]["name"])
        ai = idx_for_name(fx["teams"]["away"]["name"])
        if hi is not None and ai is not None:
            fixtures_by_pair[frozenset((hi, ai))] = fx

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    changed_count = 0
    for pair in R32_PAIRS + R16_PAIRS:
        entry = build_entry(pair, fixtures_by_pair)
        if entry is None:
            continue  # no fresh data for this match — leave the existing entry exactly as it is
        html, ok = update_entry_in_html(html, pair, entry)
        if ok:
            changed_count += 1

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Done. {changed_count} entr{'y' if changed_count==1 else 'ies'} updated with fresh fixture data; "
          f"everything else left untouched.")


if __name__ == "__main__":
    main()
