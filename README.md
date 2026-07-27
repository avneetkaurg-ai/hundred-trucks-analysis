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
| `TOKEN_SECRET` | Secret key for HMAC tracking tokens |
| `WA_TOKEN` | Meta WhatsApp API bearer token |
| `WA_PHONE_ID` | Meta WhatsApp phone number ID |
| `WA_TO` | Default WhatsApp recipient number (e.g. `+919518146736`) |

---

## Scheduled Jobs (IST)

| Time | Job | Description |
|---|---|---|
| 6 AM – 11 PM| `ping_enroute` | Fetch FASTag crossings for all live trucks (18×/day) |
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

## License

Private — Mirchi-Lime internal use only.
