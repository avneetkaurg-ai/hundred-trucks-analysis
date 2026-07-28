# Hundred Trucks — Live FASTag Tracking Dashboard

A real-time truck tracking system for **Mirchi-Lime** built on FASTag toll data. Tracks enroute trucks across India, shows live routes on a map, sends WhatsApp status reports, and lets clients follow their shipment via a public tracking link.

---

## Features

- **Live Route Map** — shows every toll plaza a truck has crossed, with a START marker (origin) and DESTINATION pin
- **Public Tracking Link** — shareable per-truck URL with HMAC token authentication so clients can track without logging in
- **Hourly FASTag Sync** — automatically fetches toll crossing data from Zoho every hour (6 AM – 11 PM IST)
- **WhatsApp Reports** — sends a daily summary + individual tracking links at 11:05 AM and 7:05 PM IST via Meta WhatsApp API and Zoho WA API
- **City + Pincode Labels** — origin and destination show city name and pincode using postalpincode.in / Nominatim geocoding
- **Neon PostgreSQL** — all trucks, crossings, and trip data stored in the cloud

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask · Gunicorn |
| Scheduler | APScheduler (cron jobs, IST timezone) |
| Database | Neon PostgreSQL (cloud) |
| Frontend | Vanilla JS · Leaflet.js |
| Hosting | Render (free tier, kept alive by UptimeRobot) |
| Data Source | Zoho Creator API (FASTag crossings, enroute trips) |
| Messaging | Meta WhatsApp API · Zoho WhatsApp API |
| Geocoding | postalpincode.in · OpenStreetMap Nominatim |

---

## Project Structure

```
hundred/
├── wsgi.py               # Flask app + APScheduler jobs + all API routes
├── hundred_trucks.html   # Main dashboard (live map, truck cards)
├── track.html            # Public tracking page (token-authenticated)
├── requirements.txt      # Python dependencies
└── ping_connected.py     # Utility: mark trucks as connected
```

---

## Environment Variables

Set these on Render (or in a `.env` file for local dev):

| Variable | Description |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `TOKEN_SECRET` | Secret key for HMAC tracking tokens (any random string) |
| `WA_TO` | Default WhatsApp recipient number (e.g. `+919518146736`) |

---

## Scheduled Jobs (IST)

| Time | Job | Description |
|---|---|---|
| 6 AM – 11 PM, :00 | `ping_enroute` | Fetch FASTag crossings for all live trucks (18×/day) |
| 9 AM, 1 PM, 6 PM | `ping_credit` | Sync credit/balance data |
| 11:05 AM & 7:05 PM | `auto_send_report` | WhatsApp summary + per-truck tracking links |

> **Night pause (12 AM – 6 AM):** FASTag pings are skipped overnight since no one monitors at night. The 6 AM ping catches all overnight crossings. This saves ~25% of Neon PostgreSQL compute usage.

> **UptimeRobot** pings the server every 5 minutes to prevent Render from sleeping, including during the overnight no-ping window.

---

## API Routes

| Endpoint | Description |
|---|---|
| `GET /api/hundred-trucks` | All trucks with latest crossing data |
| `GET /api/hundred-truck-detail?vehicle_no=` | Full crossing history for one truck |
| `GET /api/hundred-plazas` | All toll plazas |
| `GET /api/hundred-routes` | All configured routes |
| `GET /api/track?token=` | Public tracking data (token-authenticated) |
| `GET /api/make-token?vehicle_no=` | Generate a tracking token |
| `GET /api/send-report` | Manually trigger WhatsApp report |
| `GET /api/remove-enroute?vehicle_no=` | Remove a truck from enroute list |

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env   # fill in your values

# Run
python wsgi.py
```

Open `http://localhost:5000` for the dashboard.

---

## Deployment

Hosted on **Render** with a single Gunicorn worker:

```
gunicorn wsgi:application --workers 1
```

The single worker is intentional — APScheduler uses a file lock (`/tmp/hundred_scheduler.lock`) to ensure only one process runs scheduled jobs.

---

## Developer Setup

For someone picking up this project for the first time.

### 1. Database

Create a free Neon PostgreSQL database at [neon.tech](https://neon.tech). The connection string goes in `DATABASE_URL`. The app expects these tables to already exist:

- `trucks` — vehicle number, route, connected status
- `toll_crossings` — every FASTag crossing per truck
- `enroute_trips` — active long-distance trips with origin/destination
- `credit_trips` — short-distance trips within Tamil Nadu

The schema for each table is defined in the technical documentation PDF.

### 2. Zoho API

The app pulls FASTag data from a **Zoho Creator** application owned by Mirchi-Lime. You need:

- The Zoho report URL for FASTag crossings (`ZOHO_FASTAG_URL` used in `ping_enroute`)
- The Zoho WA API URL for sending WhatsApp messages (`ZOHO_WA_URL` used in `auto_send_report`)

Both URLs are already hardcoded in `wsgi.py` — no credentials needed as they use a public key in the URL. Ask the project owner if these URLs need to be updated.

### 3. How the code is organised

Everything lives in `wsgi.py`. The main flows are:

| Flow | Functions involved |
|---|---|
| FASTag sync | `ping_enroute()` → Zoho API → inserts into `toll_crossings` |
| Dashboard load | `/api/hundred-trucks` → reads `trucks` + `toll_crossings` |
| Tracking link | `/api/make-token` → HMAC token → `/api/track?token=` → `track.html` |
| WhatsApp report | `auto_send_report()` → `make_token()` per truck → Zoho WA API |
| Scheduler | `BackgroundScheduler` starts on app launch, guarded by fcntl file lock |

### 4. Common issues

| Problem | Cause | Fix |
|---|---|---|
| Scheduler not firing | Multiple workers running | Always use `--workers 1` with Gunicorn |
| `/api/send-report` crashes | `TOKEN_SECRET` not set | Add it to Render environment variables |
| WhatsApp not sending | `WA_TO` not set | Add recipient number to Render env vars |
| Neon DB sleeping | Free tier pauses after inactivity | UptimeRobot keeps Render alive; Neon wakes on first query |

---

## License

Private — Mirchi-Lime internal use only.
