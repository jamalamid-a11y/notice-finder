"""
Notice Finder -- web app.

Scrapes public-notice / foreclosure sites on demand, extracts sale date, sale
time, property address and court location, and serves them in a responsive,
filterable page that works on phone and desktop.

Routes:
  GET  /                 the UI
  GET  /api/notices      JSON list, supports ?source= &from= &to= &q=
  POST /api/refresh      re-scrape (this is the "Refresh" button)
  GET  /api/export.csv   download current filter as CSV
"""

import csv
import io
import os
import re
import sqlite3
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template, request, Response

import scrapers

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), "notices.db")
_refresh_lock = threading.Lock()
_status = {"running": False, "last_run": None, "last_count": 0, "error": None}

# Some sources (e.g. the HUD list) stamp every row with a default state even
# when the property is elsewhere in the DMV. When the property address itself
# spells out a state ("... Washington, DC 20012"), trust that over the default.
_ADDR_STATE_RE = re.compile(
    r",\s*(DC|MD|VA|District of Columbia|Maryland|Virginia)\b", re.I)
_ST_MAP = {"dc": "DC", "md": "MD", "va": "VA",
           "district of columbia": "DC", "maryland": "MD", "virginia": "VA"}


def _corrected_state(state, address):
    """Prefer an explicit state in the property address over a scraper default."""
    if address:
        matches = _ADDR_STATE_RE.findall(address)
        if matches:
            return _ST_MAP.get(matches[-1].lower(), state)
    return state


# County names arrive in many formats across sources ("County of Fairfax",
# "Fairfax County", "Fairfax", "City of Fairfax", "Fairfax City"). Canonicalize so
# each jurisdiction appears once in the filter. But a few VA/MD names are BOTH a
# county and a separate independent city — keep those distinct by tagging the city
# form "<Name> City".
_DUAL_JURIS = {"fairfax", "richmond", "roanoke", "franklin", "baltimore"}
# Counties whose official name ends in "City" (the word is part of the name).
_CITY_IN_NAME = {"james city", "charles city"}


def _normalize_county(county):
    if not county:
        return county
    c = " ".join(county.split()).strip(" ,.")
    c = c.replace("WiIliam", "William")            # observed typo (capital I)
    if c.lower() in ("frederick-va", "frederick va"):
        c = "Frederick"
    is_city = False
    m = re.match(r"(?i)^county of\s+(.+)$", c)
    if m:
        c = m.group(1)
    else:
        m = re.match(r"(?i)^city of\s+(.+)$", c)
        if m:
            c, is_city = m.group(1), True
        elif c.lower().endswith(" county"):
            c = c[:-len(" county")]
        elif c.lower().endswith(" city") and c.lower() not in _CITY_IN_NAME:
            c, is_city = c[:-len(" city")], True
    c = re.sub(r"\bOf\b", "of", c).strip()         # "Isle Of Wight" -> "Isle of Wight"
    if is_city and c.lower() in _DUAL_JURIS:
        return c + " City"
    return c


# --- storage ----------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY,
                source TEXT, publication TEXT, published_date TEXT, title TEXT,
                sale_date TEXT, sale_time TEXT, property_address TEXT,
                court_location TEXT, county TEXT, state TEXT,
                full_text TEXT, url TEXT,
                fingerprint TEXT UNIQUE
            )
        """)


def save(notices):
    rows = 0
    with db() as c:
        for n in notices:
            d = n.as_dict()
            fp = f"{d['source']}|{(d['full_text'] or '')[:200]}"
            try:
                cur = c.execute("""
                    INSERT OR IGNORE INTO notices
                    (source, publication, published_date, title, sale_date,
                     sale_time, property_address, court_location, county, state,
                     full_text, url, fingerprint)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (d["source"], d["publication"], d["published_date"],
                      d["title"], d["sale_date"], d["sale_time"],
                      d["property_address"], d["court_location"],
                      _normalize_county(d["county"]),
                      _corrected_state(d["state"], d["property_address"]),
                      d["full_text"], d["url"], fp))
                rows += cur.rowcount
            except sqlite3.Error:
                pass
    return rows


# --- scraping ---------------------------------------------------------------

def run_refresh(source_id=None, max_pages=100, exclude=()):
    if not _refresh_lock.acquire(blocking=False):
        return
    _status.update(running=True, error=None)
    try:
        total = 0
        targets = ([scrapers.get(source_id)] if source_id else scrapers.SCRAPERS)
        for sc in targets:
            if not sc or sc.source_id in exclude:
                continue
            try:
                total += save(sc.fetch(max_pages=max_pages))
            except Exception as e:  # one site failing shouldn't kill the rest
                _status["error"] = f"{sc.label}: {e}"
        _status.update(last_run=datetime.now().isoformat(timespec="seconds"),
                       last_count=total)
    finally:
        _status["running"] = False
        _refresh_lock.release()


# --- query ------------------------------------------------------------------

def query(source=None, dfrom=None, dto=None, q=None, counties=None, state=None):
    sql = "SELECT * FROM notices WHERE 1=1"
    args = []
    if source:
        sql += " AND source=?"; args.append(source)
    if state:
        sql += " AND state=?"; args.append(state)
    counties = [c for c in (counties or []) if c]
    if counties:
        sql += " AND county IN (%s)" % ",".join("?" * len(counties))
        args += counties
    if dfrom:
        sql += " AND sale_date>=?"; args.append(dfrom)
    if dto:
        sql += " AND sale_date<=?"; args.append(dto)
    if q:
        sql += (" AND (full_text LIKE ? OR property_address LIKE ?"
                " OR court_location LIKE ? OR publication LIKE ?)")
        like = f"%{q}%"; args += [like, like, like, like]
    sql += " ORDER BY (sale_date IS NULL), sale_date ASC"
    with db() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


# --- routes -----------------------------------------------------------------

@app.route("/")
def index():
    sources = [{"id": s.source_id, "label": s.label} for s in scrapers.SCRAPERS]
    return render_template("index.html", sources=sources)


@app.route("/api/notices")
def api_notices():
    rows = query(request.args.get("source"), request.args.get("from"),
                 request.args.get("to"), request.args.get("q"),
                 request.args.getlist("county"), request.args.get("state"))
    everything = query()
    states = sorted({r["state"] for r in everything if r.get("state")})
    by_state = {}
    for r in everything:
        if r.get("state") and r.get("county"):
            by_state.setdefault(r["state"], set()).add(r["county"])
    counties_by_state = {s: sorted(v) for s, v in by_state.items()}
    return jsonify({"status": _status, "count": len(rows), "notices": rows,
                    "states": states, "counties_by_state": counties_by_state})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    source = (request.json or {}).get("source") if request.is_json else None
    threading.Thread(target=run_refresh, kwargs={"source_id": source},
                     daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/status")
def api_status():
    return jsonify(_status)


@app.route("/api/export.csv")
def export_csv():
    rows = query(request.args.get("source"), request.args.get("from"),
                 request.args.get("to"), request.args.get("q"),
                 request.args.getlist("county"), request.args.get("state"))
    cols = ["source", "publication", "sale_date", "sale_time",
            "property_address", "county", "state", "court_location",
            "published_date", "url"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=notices.csv"})


init_db()

# Free-tier instances have no persistent disk: the DB is wiped on every deploy
# and whenever the instance sleeps. So on startup, auto-pull the fast sources
# (everything except the slow Virginia portal) in the background — that way the
# app shows next-week sales within ~30s of waking, with no manual Refresh.
def _startup_refresh():
    with db() as c:
        existing = c.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    if existing == 0:
        run_refresh(exclude={"va"})

threading.Thread(target=_startup_refresh, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
