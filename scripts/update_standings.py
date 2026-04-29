
#!/usr/bin/env python3
"""
Update team goal totals + recent finished matches using football-data.org.

Outputs:
  standings/teams.json            (GF/GA/GD/Played for sweepstake teams)
  standings/recent_finished.json  (last 5 FINISHED matches involving sweepstake teams)

The webpage can compute the ticket league table client-side from:
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

import os
import json
from datetime import datetime
import urllib.request
import urllib.parse


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

HEADERS = {
    "X-Auth-Token": TOKEN,
    "User-Agent": "wc2026-sweepstake/1.0"
}


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

    # Fallback: find something with "World Cup" in name
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
    """
    Goals counting normal+ET but excluding shootouts.

    football-data.org:
      - fullTime: running/final score
      - regularTime: 90-min score when ET/penalties occur
      - extraTime: ET-only goals
      - penalties: shootout goals (ignored)
      - duration indicates REGULAR/EXTRA_TIME/PENALTY_SHOOTOUT
    """
    if not score:
        return 0, 0

    duration = score.get("duration")
    ft_h, ft_a = pair(score.get("fullTime") or {})
    rt = score.get("regularTime") or None
    et = score.get("extraTime") or None

    base_h, base_a = pair(rt) if rt else (ft_h, ft_a)
    et_h, et_a = pair(et) if et else (0, 0)

    if duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        return base_h + et_h, base_a + et_a

    # REGULAR: fullTime already excludes shootout scores
    return ft_h, ft_a


def display_scores(score):
    """
    For display in 'recent finished' list:

    - FT shown as regularTime if present (90 mins), else fullTime
    - ET shown as extraTime if match went to extra time / penalties
    """
    if not score:
        return 0, 0, None

    duration = score.get("duration")
    ft_node = score.get("regularTime") or score.get("fullTime") or {}
    ft_h, ft_a = pair(ft_node)

    if duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        et_node = score.get("extraTime") or {}
        et_h, et_a = pair(et_node)
        return ft_h, ft_a, {"home": et_h, "away": et_a}

    return ft_h, ft_a, None


def main():
    # Load tickets and optional team name mapping
    with open(TICKETS_PATH, "r", encoding="utf-8") as f:
        tickets = json.load(f)

    with open(MAP_PATH, "r", encoding="utf-8") as f:
        name_map = json.load(f)

    # Sweepstake teams are from your tickets.json (after mapping)
    sweep_teams = sorted({name_map.get(t, t) for tk in tickets for t in tk["teams"]})

    # Fetch matches
    comp_id = find_competition_id(COMP_CODE)
    data = http_get(f"/competitions/{comp_id}/matches", {"season": SEASON_YEAR})
    matches = data.get("matches", [])

    # Aggregate stats
    team_stats = {t: {"team": t, "gf": 0, "ga": 0, "gd": 0, "played": 0} for t in sweep_teams}
    finished_relevant = []

    for m in matches:
        status = m.get("status")
        if status in ("SCHEDULED", "TIMED", "POSTPONED", "CANCELED", "SUSPENDED"):
            continue

        home = (m.get("homeTeam") or {}).get("name")
        away = (m.get("awayTeam") or {}).get("name")

        # Only track matches where BOTH teams are in your sweepstake list
        if home not in team_stats or away not in team_stats:
            continue

        ch, ca = counted_goals(m.get("score"))

        team_stats[home]["gf"] += ch
        team_stats[home]["ga"] += ca
        team_stats[away]["gf"] += ca
        team_stats[away]["ga"] += ch

        if status == "FINISHED":
            team_stats[home]["played"] += 1
            team_stats[away]["played"] += 1

            ft_h, ft_a, et = display_scores(m.get("score") or {})
            finished_relevant.append({
                "utcDate": m.get("utcDate"),
                "home": home,
                "away": away,
                "ft": {"home": ft_h, "away": ft_a},
                "et": et,
                "duration": (m.get("score") or {}).get("duration"),
                "matchId": m.get("id")
            })

    for st in team_stats.values():
        st["gd"] = st["gf"] - st["ga"]

    # Last 5 finished, most recent first
    finished_relevant.sort(key=lambda x: x.get("utcDate") or "", reverse=True)
    recent5 = finished_relevant[:5]

    generated_at = datetime.utcnow().isoformat() + "Z"

    # Write outputs
    with open(OUT_TEAMS, "w", encoding="utf-8") as f:
        json.dump({"generated_at": generated_at, "teams": list(team_stats.values())},
                  f, ensure_ascii=False, indent=2)

    with open(OUT_RECENT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": generated_at, "matches": recent5},
                  f, ensure_ascii=False, indent=2)

    print(f"OK: wrote {OUT_TEAMS} and {OUT_RECENT}")


if __name__ == "__main__":
    main()
