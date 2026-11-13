"""Booking, search and inventory rules, kept apart from the Flask routes so they can be tested directly."""
from datetime import date, timedelta

VEHICLE_TYPES = ["Compact", "Sedan", "SUV", "Van","Sports Car"]
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


# ---------- Rental history (customer) ----------

def rental_history(db, user_id, today):
    """Completed rentals for one customer, most recent first.

    A rental moves into the history once its return date has passed (rentals due back today still
    show as upcoming); cancelled bookings are included so the customer can see them, marked as such.
    """
    rows = db.execute(
        """SELECT r.id, r.pickup_date, r.return_date, r.total, r.status, r.extras, r.branch,
                  v.name, v.year, v.type, v.plate, v.image
           FROM reservations r JOIN vehicles v ON v.id = r.vehicle_id
           WHERE r.user_id = ? AND (r.return_date < ? OR r.status = 'cancelled')
           ORDER BY r.pickup_date DESC, r.id DESC""",
        [user_id, today.isoformat()]).fetchall()
    return [{**dict(r), "days": (date.fromisoformat(r["return_date"])
                                 - date.fromisoformat(r["pickup_date"])).days}
            for r in rows]


# ---------- Fleet management (staff) ----------

VEHICLE_STATUSES = {"active": "Active", "maintenance": "In maintenance", "retired": "Retired"}
TRANSMISSIONS = ["Automatic", "Manual"]
FUELS = ["Gasoline", "Hybrid", "Electric", "Diesel"]
MIN_YEAR = 1990


def parse_vehicle(form, this_year):
    """Validate the add/edit vehicle form. Returns a dict of clean values or raises ValueError."""
    def text(field, label, max_len=40):
        value = (form.get(field) or "").strip()
        if not value:
            raise ValueError(f"{label} is required.")
        if len(value) > max_len:
            raise ValueError(f"{label} must be at most {max_len} characters.")
        return value

    def number(field, label, cast, low, high):
        try:
            value = cast(form.get(field))
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a number.")
        if not low <= value <= high:
            raise ValueError(f"{label} must be between {low} and {high}.")
        return value

    vehicle = {
        "make": text("make", "Make"),
        "model": text("model", "Model"),
        "plate": text("plate", "Plate", 10).upper(),
        "year": number("year", "Year", int, MIN_YEAR, this_year + 1),
        "seats": number("seats", "Seating capacity", int, 1, 15),
        "daily_rate": number("daily_rate", "Daily rate", float, 1, 1000),
        "type": form.get("type"),
        "transmission": form.get("transmission"),
        "fuel": form.get("fuel"),
        "status": form.get("status", "active"),
    }
    if vehicle["daily_rate"] != round(vehicle["daily_rate"], 2):
        raise ValueError("Daily rate can have at most two decimal places.")
    if vehicle["type"] not in VEHICLE_TYPES:
        raise ValueError("Choose a vehicle type.")
    if vehicle["transmission"] not in TRANSMISSIONS:
        raise ValueError("Choose a transmission.")
    if vehicle["fuel"] not in FUELS:
        raise ValueError("Choose a fuel type.")
    if vehicle["status"] not in ("active", "maintenance"):
        raise ValueError("Availability must be Active or In maintenance. Use Retire to remove a car.")
    return vehicle


def upcoming_bookings(db, vehicle_id, today):
    """Confirmed bookings that have not finished yet; a car with any of these can't be retired."""
    return db.execute(
        "SELECT id, pickup_date, return_date FROM reservations"
        " WHERE vehicle_id = ? AND status = 'confirmed' AND return_date > ? ORDER BY pickup_date",
        [vehicle_id, today.isoformat()]).fetchall()


# ---------- Vehicle utilization report (staff) ----------

def overlap_days(pickup, return_date, start, end):
    """Days of a rental [pickup, return_date) that fall inside the report range [start, end] (inclusive)."""
    first = max(pickup, start)
    last = min(return_date, end + timedelta(days=1))
    return max(0, (last - first).days)


def utilization(db, start, end):
    """Per-category rental statistics for the inclusive date range [start, end].

    For each vehicle type:
      rentals        - confirmed rentals that overlap the range
      rental_days    - rented days that fall inside the range
      fleet          - cars that could have been rented: in service, or rented during the range
      rentals_per_car- rental frequency (rentals / fleet)
      utilization    - rental_days / (fleet * days in range), as a percentage
      avg_length     - average full length of those rentals, in days
    """
    if end < start:
        raise ValueError("The end date must be on or after the start date.")
    range_days = (end - start).days + 1

    bookings = db.execute(
        """SELECT r.vehicle_id, r.pickup_date, r.return_date, v.type
           FROM reservations r JOIN vehicles v ON v.id = r.vehicle_id
           WHERE r.status = 'confirmed' AND r.pickup_date <= :end AND r.return_date > :start""",
        {"start": start.isoformat(), "end": end.isoformat()}).fetchall()
    vehicles = db.execute("SELECT id, type, status FROM vehicles").fetchall()

    rented_ids = {b["vehicle_id"] for b in bookings}
    stats = {t: {"type": t, "rentals": 0, "rental_days": 0, "total_length": 0, "fleet": 0}
             for t in VEHICLE_TYPES}
    for v in vehicles:
        if v["status"] != "retired" or v["id"] in rented_ids:
            stats[v["type"]]["fleet"] += 1
    for b in bookings:
        pickup, ret = date.fromisoformat(b["pickup_date"]), date.fromisoformat(b["return_date"])
        s = stats[b["type"]]
        s["rentals"] += 1
        s["rental_days"] += overlap_days(pickup, ret, start, end)
        s["total_length"] += (ret - pickup).days

    rows = []
    for s in stats.values():
        capacity = s["fleet"] * range_days
        rows.append({
            **s,
            "rentals_per_car": round(s["rentals"] / s["fleet"], 2) if s["fleet"] else 0.0,
            "utilization": round(100 * s["rental_days"] / capacity, 1) if capacity else 0.0,
            "avg_length": round(s["total_length"] / s["rentals"], 1) if s["rentals"] else 0.0,
        })
    total_fleet = sum(r["fleet"] for r in rows)
    total_days = sum(r["rental_days"] for r in rows)
    totals = {
        "rentals": sum(r["rentals"] for r in rows),
        "rental_days": total_days,
        "fleet": total_fleet,
        "utilization": round(100 * total_days / (total_fleet * range_days), 1) if total_fleet else 0.0,
    }
    return {"rows": rows, "totals": totals, "range_days": range_days}
