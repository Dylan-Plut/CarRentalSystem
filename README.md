# Car Rental System – Sprint 01 Prototype (Group 31)

Flask + SQLite prototype covering the four Sprint 01 stories:

| Story | Where |
|---|---|
| Filter Cars | Customer → **Find a car** (`/search`) |
| Vehicle Booking | Customer → **Vehicle details** → *Reserve this car* (`/vehicles/<id>`) |
| Inventory Tracking | Staff → **Dashboard** (`/staff`) |
| Vehicle Damage | Staff → **Fleet** → vehicle record → *Damage log* (`/staff/fleet`) |

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
- `rentals.py` – search, availability, pricing and inventory rules
- `db.py` / `schema.sql` – SQLite connection, tables and seed data
- `templates/`, `static/style.css` – pages based on the Milestone 02 mock-ups

Vehicle photos come from Wikimedia Commons (CC BY-SA); see [static/cars/CREDITS.md](static/cars/CREDITS.md).
