"""Booking, search and inventory rules, kept apart from the Flask routes so they can be tested directly."""
from datetime import date, timedelta

VEHICLE_TYPES = ["Compact", "Sedan", "SUV", "Van"]
BRANCH = "Waterloo – King St N"
TAX_RATE = 0.13
MAX_RENTAL_DAYS = 30
RESERVED_WINDOW_DAYS = 2  # a car being picked up this soon is shown to staff as "Reserved"

EXTRAS = {
    "insurance": ("Extra insurance coverage", 15.00),
    "child_seat": ("Child seat", 8.00),
}

DAMAGE_AREAS = ["Front bumper", "Rear bumper", "Driver door", "Passenger door", "Hood",
                "Roof", "Windshield", "Wheel / tire", "Interior"]
DAMAGE_KINDS = ["Scratch", "Dent", "Chip", "Crack", "Stain", "Other"]
DAMAGE_STATUSES = {"needs_review": "Needs review", "repair_booked": "Repair booked", "fixed": "Fixed"}

# A car is bookable when it is in service and no confirmed booking overlaps the requested dates.
AVAILABLE_SQL = """
    SELECT v.* FROM vehicles v
    WHERE v.status = 'active'
      AND NOT EXISTS (
          SELECT 1 FROM reservations r
          WHERE r.vehicle_id = v.id
            AND r.status = 'confirmed'
            AND r.pickup_date < :dropoff
            AND r.return_date > :pickup)
"""


def parse_trip(pickup, dropoff, today):
    """Turn the two date strings from a form into dates, or raise ValueError with a message for the user."""
    try:
        start, end = date.fromisoformat(pickup), date.fromisoformat(dropoff)
    except (TypeError, ValueError):
        raise ValueError("Please choose a pick-up and return date.")
    if start < today:
        raise ValueError("Pick-up date can't be in the past.")
    if end <= start:
        raise ValueError("Return date must be after the pick-up date.")
    if (end - start).days > MAX_RENTAL_DAYS:
        raise ValueError(f"Rentals can be at most {MAX_RENTAL_DAYS} days.")
    return start, end


def search_vehicles(db, pickup, dropoff, vtype=None, max_price=None, min_seats=None, sort="price_asc"):
    sql = AVAILABLE_SQL
    params = {"pickup": pickup.isoformat(), "dropoff": dropoff.isoformat()}
    if vtype:
        sql += " AND v.type = :vtype"
        params["vtype"] = vtype
    if max_price:
        sql += " AND v.daily_rate <= :max_price"
        params["max_price"] = max_price
    if min_seats:
        sql += " AND v.seats >= :min_seats"
        params["min_seats"] = min_seats
    sql += " ORDER BY v.daily_rate DESC" if sort == "price_desc" else " ORDER BY v.daily_rate"
    return db.execute(sql, params).fetchall()


def is_available(db, vehicle_id, pickup, dropoff):
    params = {"pickup": pickup.isoformat(), "dropoff": dropoff.isoformat(), "id": vehicle_id}
    return db.execute(AVAILABLE_SQL + " AND v.id = :id", params).fetchone() is not None


def quote(car, pickup, dropoff, extras=()):
    days = (dropoff - pickup).days
    base = car["daily_rate"] * days
    extras_total = sum(EXTRAS[e][1] for e in extras) * days
    taxes = round((base + extras_total) * TAX_RATE, 2)
    return {
        "days": days,
        "base": base,
        "extras": extras_total,
        "taxes": taxes,
        "total": round(base + extras_total + taxes, 2),
    }


def inventory(db, today):
    """Every in-service car with its status for today, as shown on the staff dashboard."""
    vehicles = db.execute(
        "SELECT * FROM vehicles WHERE status != 'retired' ORDER BY type, model").fetchall()
    bookings = db.execute(
        "SELECT vehicle_id, pickup_date, return_date FROM reservations"
        " WHERE status = 'confirmed' AND return_date >= ? ORDER BY pickup_date",
        [today.isoformat()]).fetchall()

    by_vehicle = {}
    for b in bookings:
        by_vehicle.setdefault(b["vehicle_id"], []).append(b)

    today_s = today.isoformat()
    soon = (today + timedelta(days=RESERVED_WINDOW_DAYS)).isoformat()
    rows = []
    for v in vehicles:
        booked = by_vehicle.get(v["id"], [])
        current = next((b for b in booked if b["pickup_date"] <= today_s), None)
        upcoming = next((b for b in booked if b["pickup_date"] > today_s), None)

        if v["status"] == "maintenance":
            status, next_booking = "Maintenance", "—"
        elif current:
            status, next_booking = "On rent", f"Due {current['return_date']}"
        elif upcoming and upcoming["pickup_date"] <= soon:
            status, next_booking = "Reserved", upcoming["pickup_date"]
        else:
            status, next_booking = "Available", upcoming["pickup_date"] if upcoming else "None"

        rows.append({
            **dict(v),
            "state": status,
            "next_booking": next_booking,
            "due_today": bool(current and current["return_date"] == today_s),
        })
    return rows
