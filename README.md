# Car Rental System – Sprint 01 Prototype (Group 31)

Flask + SQLite prototype covering the four Sprint 01 stories:

| Story | Where |
|---|---|
| Filter Cars | Customer → **Find a car** (`/search`) |
| Vehicle Booking | Customer → **Vehicle details** → *Reserve this car* (`/vehicles/<id>`) |
| Inventory Tracking | Staff → **Dashboard** (`/staff`) |
| Vehicle Damage | Staff → **Fleet** → vehicle record → *Damage log* (`/staff/fleet`) |

### Sprint 02

| Story | Where |
|---|---|
| Rental History | Customer → **My Rentals** → *Rental history* (`/rentals`) – past rentals, newest first, with ID, vehicle, dates, duration and total |
| Manage Fleet (ADM-2) | Staff → **Fleet** → *+ Add vehicle* (`/staff/vehicles/new`), *Edit details*, *Retire* / *Reinstate* on a vehicle record |
| Vehicle Utilization Report (REP-1) | Staff → **Reports** (`/staff/reports`) – rentals, days rented, rentals per car and utilization % per category for a date range |

Tests: `python -m unittest -v`

The demo database is rebuilt automatically when the schema version changes (or run `flask --app app init-db`).

## Run it

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

Demo accounts (password `password`):

- `customer@example.com` – customer app
- `staff@example.com` – staff portal

## Layout

- `app.py` – routes for the customer app and staff portal
- `rentals.py` – search, availability, pricing, inventory, rental history, fleet validation and utilization rules
- `db.py` / `schema.sql` – SQLite connection, tables and seed data
- `test_app.py` – Sprint 02 tests
- `templates/`, `static/style.css` – pages based on the Milestone 02 mock-ups

Vehicle photos come from Wikimedia Commons (CC BY-SA); see [static/cars/CREDITS.md](static/cars/CREDITS.md).
