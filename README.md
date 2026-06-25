# Notice Finder

A web app that searches public-notice / foreclosure sites, pulls all result
pages, and extracts **sale date, sale time, property address and court
location** into one filterable list. Works on phone and desktop. A **Refresh**
button re-pulls the latest on demand.

## Try it on your PC first

1. Install Python 3.12 from python.org (tick "Add to PATH").
2. In a terminal, from this folder:
   ```
   pip install -r requirements.txt
   python app.py
   ```
3. Open http://localhost:5000 and click **Refresh data**.

## Put it online (free, reachable from your phone)

The app is ready for [Render](https://render.com)'s free tier:

1. Put this folder in a GitHub repo (free GitHub account).
2. On Render: **New + → Blueprint**, connect the repo. `render.yaml` does the rest.
3. Render gives you a URL like `https://notice-finder.onrender.com` — open it
   on your PC or phone, add it to your home screen.

Note: the free tier sleeps after inactivity, so the first open after a while
takes ~30s to wake. Upgrading to the $7/mo plan keeps it always awake.

## Adding your other sites

Each site is one file in `scrapers/`. Copy `scrapers/virginia.py`, rename the
class and `source_id`, rewrite `fetch()` for the new site, then add it to the
list in `scrapers/__init__.py`. The UI, filtering and CSV export pick it up
automatically.

## How field extraction works

Public notices are free-form legal text, so `parsers.py` uses pattern-matching
to pull out the sale date/time and addresses. It handles the common phrasings;
unusual notices may leave a field blank, which is why the full notice text is
always kept and shown under "Full notice".
