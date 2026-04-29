#!/usr/bin/env python3
"""Update team goal totals + recent finished matches using football-data.org.

Outputs:
  standings/teams.json            (GF/GA/GD/Played for sweepstake teams)
  standings/recent_finished.json  (last 5 finished matches involving sweepstake teams)

The webpage computes the ticket league table client-side from:
  - data/tickets.json
  - standings/teams.json

Scoring:
  - count goals in normal time + extra time
  - exclude penalty shootout goals

Env:
  FOOTBALL_DATA_TOKEN (required)
  COMPETITION_CODE (default WC)
  SEASON_YEAR (default 2026)
"""

import os, json
from datetime import datetime
import urllib.request, urllib.parse

BASE = "https://api.football-data.org/v4"
TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")
if not TOKEN:
    raise SystemExit("Missing env FOOTBALL_DATA_TOKEN")

COMP_CODE = os.environ.get("COMPETITION_CODE", "WC")
SEASON_YEAR = os.environ.get("SEASON_YEAR", "2026")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKETS_PATH = os.path.join(ROOT, "data", "tickets.json")
MAP_PATH = os.path.join(ROOT, "data", "team_name_map.json")
OUT_TEAMS = os.path.join(ROOT, "standings", "teams.json")
OUT_RECENT = os.path.join(ROOT, "standings", "recent_finished.json")

HEADERS = {"X-Auth-Token": TOKEN, "User-Agent": "wc2026-sweepstake/1.0"}

def http_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def find_competition_id(code):
    data = http_get("/competitions")
    for c in data.get("competitions", []):
        if c.get("code") == code:
            return c.get("id")
    for c in data.get("competitions", []):
        nm = (c.get("name") or "").lower()
        if "world" in nm and "cup" in nm:
            return c.get("id")
    raise RuntimeError(f"Could not find competition id for code={code}")

def safe_int(x):
    return 0 if x is None else int(x)

def pair(d):
    if not d:
        return 0, 0
    return safe_int(d.get("home")), safe_int(d.get("away"))

def counted_goals(score):
    """Goals counting normal+ET but excluding shootouts."""
    if not score:
        return 0, 0
    duration = score.get("duration")
    ft_h, ft_a = pair(score.get("fullTime") or {})
    rt = score.get("regularTime")
    et = score.get("extraTime")
    base_h, base_a = pair(rt) if rt else (ft_h, ft_a)
    et_h, et_a = pair(et)
    if duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        return base_h + et_h, base_a + et_a
    return ft_h, ft_a

def display_scores(score):
    """Return (ft_home, ft_away, et_home, et_away, has_et).

    For display:
      - FT = regularTime if present (90 mins), else fullTime
      - ET = extraTime if duration indicates extra time or penalties
    """
    if not score:
        return 0, 0, 0, 0, False
    duration = score.get("duration")
    ft = score.get("regularTime") or score.get("fullTime") or {}
    et = score.get("extraTime") or {}
    ft_h, ft_a = pair(ft)
    et_h, et_a = pair(et)
    has_et = duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT")
    return ft_h, ft_a, et_h, et_a, has_et

def main():
    tickets = json.load(open(TICKETS_PATH,'r',encoding='utf-8'))
    name_map = json.load(open(MAP_PATH,'r',encoding='utf-8'))
    sweep_teams = sorted({name_map.get(t,t) for tk in tickets for t in tk['teams']})

    comp_id = find_competition_id(COMP_CODE)
    matches = http_get(f"/competitions/{comp_id}/matches", {"season": SEASON_YEAR}).get('matches', [])

    team_stats = {t: {"team": t, "gf": 0, "ga": 0, "gd": 0, "played": 0} for t in sweep_teams}
    finished_relevant = []

    for m in matches:
        status = m.get('status')
        home = (m.get('homeTeam') or {}).get('name')
        away = (m.get('awayTeam') or {}).get('name')

        if status in ("SCHEDULED","TIMED","POSTPONED","CANCELED","SUSPENDED"):
            continue

        ch, ca = counted_goals(m.get('score'))

        # Update only if both teams are in the sweepstake list
        if home in team_stats and away in team_stats:
            team_stats[home]['gf'] += ch
            team_stats[home]['ga'] += ca
            team_stats[away]['gf'] += ca
            team_stats[away]['ga'] += ch

            if status == 'FINISHED':
                team_stats[home]['played'] += 1
                team_stats[away]['played'] += 1

                ft_h, ft_a, et_h, et_a, has_et = display_scores(m.get('score'))
                finished_relevant.append({
                    "utcDate": m.get('utcDate'),
                    "home": home,
                    "away": away,
                    "ft": {"home": ft_h, "away": ft_a},
                    "et": {"home": et_h, "away": et_a} if has_et else None,
                    "duration": (m.get('score') or {}).get('duration'),
                    "matchId": m.get('id')
                })

    for st in team_stats.values():
        st['gd'] = st['gf'] - st['ga']

    # Sort finished matches by utcDate desc and keep last 5
    finished_relevant.sort(key=lambda x: x.get('utcDate') or '', reverse=True)
    recent5 = finished_relevant[:5]

    generated_at = datetime.utcnow().isoformat() + 'Z'
    json.dump({"generated_at": generated_at, "teams": list(team_stats.values())}, open(OUT_TEAMS,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump({"generated_at": generated_at, "matches": recent5}, open(OUT_RECENT,'w',encoding='utf-8'), ensure_ascii=False, indent=2)

if __name__=='__main__':
    main()
