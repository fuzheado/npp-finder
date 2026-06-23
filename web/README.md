# npp-finder Web Dashboard

A lightweight web dashboard for scanning new Wikipedia pages for URL-free
references — designed for Toolforge Kubernetes deployment and local development.

## Quick start

```bash
# From the repo root, install npp-finder + web dependencies
cd /path/to/npp-finder
pip install -e .
pip install -r web/requirements.txt

# Run the dashboard
cd web
python app.py
```

Open http://localhost:8080 — the form lets you set `--days` and `--limit`
and shows results in a sortable table with clickable Wikipedia links.

## Deployment on Toolforge Kubernetes

### Prerequisites

- A [Toolforge](https://toolforge.org) account
- Your tool created (`become <toolname>`)

### Steps

```bash
# 1. SSH to Toolforge and set up
ssh <username>@login.toolforge.org
become <toolname>

# 2. Clone the repo
git clone https://github.com/fuzheado/npp-finder.git ~/npp-finder

# 3. Set up Python environment
python3 -m venv ~/npp-finder/venv
source ~/npp-finder/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install ~/npp-finder/
pip install -r ~/npp-finder/web/requirements.txt

# 4. Start the web service
webservice --backend=kubernetes python3.11 start \
  --command "~/npp-finder/venv/bin/uvicorn app:app --host 0.0.0.0 --port \$PORT"
```

### Configuration

The app reads `PORT` from the environment (Toolforge sets this automatically).
Default is 8080.

### Notes

- **Long scans:** A scan of 500 pages with quality predictions can take 60s+.
  For the web UI, keep defaults low (50–100 pages) for reasonable wait times.
- **Results are cached** to `web/results.json` so re-visiting the page shows
  the last scan without re-running it.
- **Concurrent scans are blocked** — only one scan runs at a time (per pod).
- **No authentication** — this is a read-only public tool. The Wikipedia API
  doesn't need auth for reads.

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Home page with cached results |
| `/scan` | GET | Scan form |
| `/scan` | POST | Run a scan and show results |
| `/api/results` | GET | Cached scan results as JSON |
| `/api/scan` | POST | Run a scan, return JSON |
