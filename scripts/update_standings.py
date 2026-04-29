#!/usr/bin/env python3
"""Update sweepstake standings + team goal totals using football-data.org.

Counts goals in normal + extra time; excludes penalty shootout goals.

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
OUT_STANDINGS = os.path.join(ROOT, "standings", "standings.json")
OUT_TEAMS = os.path.join(ROOT, "standings", "teams.json")

HEADERS = {"X-Auth-Token": TOKEN, "User-Agent": "wc2026-sweepstake/1.0"}

def http_get(path, params=None):
    url = BASE + path
    if params:
        qs = urllib.parse.urlencode(params)
        url = url + "?" + qs
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def find_competition_id(code):
    data = http_get("/competitions")
    for c in data.get("competitions", []):
        if c.get("code") == code:
            return c.get("id")
    for c in data.get("competitions", []):
        name = (c.get("name") or "").lower()
        if "world" in name and "cup" in name:
            return c.get("id")
    raise RuntimeError(f"Could not find competition id for code={code}")

def safe_int(x):
    return 0 if x is None else int(x)

def pair(d):
    if not d:
        return 0, 0
    return safe_int(d.get("home")), safe_int(d.get("away"))

def counted_goals(score):
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

def main():
    tickets = json.load(open(TICKETS_PATH, 'r', encoding='utf-8'))
    name_map = json.load(open(MAP_PATH, 'r', encoding='utf-8'))

    sweep_teams = sorted({name_map.get(t, t) for tk in tickets for t in tk['teams']})
    comp_id = find_competition_id(COMP_CODE)
    matches = http_get(f"/competitions/{comp_id}/matches", {"season": SEASON_YEAR}).get('matches', [])

    team_stats = {t: {"team": t, "gf": 0, "ga": 0, "gd": 0, "played": 0} for t in sweep_teams}

    for m in matches:
        status = m.get('status')
        if status in ("SCHEDULED","TIMED","POSTPONED","CANCELED","SUSPENDED"):
            continue
        home = (m.get('homeTeam') or {}).get('name')
        away = (m.get('awayTeam') or {}).get('name')
        ch, ca = counted_goals(m.get('score'))
        if home in team_stats and away in team_stats:
            team_stats[home]['gf'] += ch
            team_stats[home]['ga'] += ca
            team_stats[away]['gf'] += ca
            team_stats[away]['ga'] += ch
            if status == 'FINISHED':
                team_stats[home]['played'] += 1
                team_stats[away]['played'] += 1

    for st in team_stats.values():
        st['gd'] = st['gf'] - st['ga']

    standings=[]
    for tk in tickets:
        teams=[name_map.get(t,t) for t in tk['teams']]
        goals=sum(team_stats.get(t,{}).get('gf',0) for t in teams)
        gd=sum(team_stats.get(t,{}).get('gd',0) for t in teams)
        standings.append({"ticket": tk['ticket'], "owner": tk['owner'], "teams": teams, "goals": goals, "gd": gd, "rank": tk.get('rank', tk['ticket'])})

    standings.sort(key=lambda x: (x['goals'], x['gd'], x['rank']), reverse=True)
    for i,row in enumerate(standings,1):
        row['position']=i

    generated_at = datetime.utcnow().isoformat() + 'Z'
    json.dump({"generated_at": generated_at, "teams": list(team_stats.values())}, open(OUT_TEAMS,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump({"generated_at": generated_at, "competition_code": COMP_CODE, "season": SEASON_YEAR, "standings": standings}, open(OUT_STANDINGS,'w',encoding='utf-8'), ensure_ascii=False, indent=2)

if __name__=='__main__':
    main()
