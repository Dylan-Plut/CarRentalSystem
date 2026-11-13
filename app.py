"""Car Rental System – Sprint 02 (Group 31).

Customer app: sign in, search & filter cars, view details, reserve, rental history.
Staff portal: vehicle availability dashboard, fleet management (add / edit / retire) with damage log,
vehicle utilization report.
"""
import os
import sqlite3
from collections import Counter
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import db as database
import rentals
from db import get_db

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    DATABASE=os.environ.get("DATABASE", str(Path(app.root_path) / "rental.db")),
)
database.init_app(app)


@app.context_processor
def template_globals():
    return {"today": date.today().isoformat(), "branch": rentals.BRANCH}


@app.template_filter("extra_name")
def extra_name(key):
    return rentals.EXTRAS.get(key, (key,))[0]


def login_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ---------- Sign in (routes by role) ----------

@app.get("/")
def index():
    if session.get("role") == "staff":
        return redirect(url_for("dashboard"))
    if session.get("role") == "customer":
        return redirect(url_for("search"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", [email]).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], role=user["role"], name=user["name"])
            return redirect(url_for("index"))
        flash("Email or password is incorrect.")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Customer app ----------

def default_trip():
    start = date.today() + timedelta(days=1)
    return start, start + timedelta(days=3)


@app.get("/search")
@login_required("customer")
def search():
    args = request.args
    try:
        pickup, dropoff = rentals.parse_trip(args["pickup"], args["dropoff"], date.today())
    except KeyError:
        pickup, dropoff = default_trip()
    except ValueError as e:
        flash(str(e))
        pickup, dropoff = default_trip()

    vtype = args.get("type") if args.get("type") in rentals.VEHICLE_TYPES else None
    max_price = args.get("max_price", 150, type=int)
    min_seats = args.get("seats", type=int)
    sort = args.get("sort", "price_asc")

    cars = rentals.search_vehicles(get_db(), pickup, dropoff, vtype, max_price, min_seats, sort)
    filters = {"pickup": pickup.isoformat(), "dropoff": dropoff.isoformat(), "type": vtype,
               "max_price": max_price, "seats": min_seats, "sort": sort}
    return render_template("search.html", cars=cars, f=filters, types=rentals.VEHICLE_TYPES)


def load_car(vehicle_id):
    car = get_db().execute(
        "SELECT * FROM vehicles WHERE id = ? AND status != 'retired'", [vehicle_id]).fetchone()
    if car is None:
        abort(404)
    return car


@app.get("/vehicles/<int:vehicle_id>")
@login_required("customer")
def vehicle(vehicle_id):
    car = load_car(vehicle_id)
    try:
        pickup, dropoff = rentals.parse_trip(
            request.args.get("pickup"), request.args.get("dropoff"), date.today())
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("search"))

    db = get_db()
    damage = db.execute(
        "SELECT * FROM damage_reports WHERE vehicle_id = ? AND status != 'fixed' ORDER BY reported_at DESC",
        [vehicle_id]).fetchall()
    return render_template(
        "vehicle.html", car=car, damage=damage, extras=rentals.EXTRAS, tax_rate=rentals.TAX_RATE,
        pickup=pickup.isoformat(), dropoff=dropoff.isoformat(),
        q=rentals.quote(car, pickup, dropoff),
        available=rentals.is_available(db, vehicle_id, pickup, dropoff))


@app.post("/vehicles/<int:vehicle_id>/reserve")
@login_required("customer")
def reserve(vehicle_id):
    car = load_car(vehicle_id)
    try:
        pickup, dropoff = rentals.parse_trip(
            request.form.get("pickup"), request.form.get("dropoff"), date.today())
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("search"))
    extras = [e for e in request.form.getlist("extras") if e in rentals.EXTRAS]

    db = get_db()
    # Take the write lock before checking, so two customers can't both book the last free slot.
    db.execute("BEGIN IMMEDIATE")
    if not rentals.is_available(db, vehicle_id, pickup, dropoff):
        db.rollback()
        flash("Sorry, that car was just booked for those dates. Please pick another.")
        return redirect(url_for("search", pickup=pickup.isoformat(), dropoff=dropoff.isoformat()))

    total = rentals.quote(car, pickup, dropoff, extras)["total"]
    cur = db.execute(
        "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, branch, extras, total)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [session["user_id"], vehicle_id, pickup.isoformat(), dropoff.isoformat(),
         rentals.BRANCH, ",".join(extras), total])
    db.commit()
    return redirect(url_for("my_rentals", confirmed=cur.lastrowid))


@app.get("/rentals")
@login_required("customer")
def my_rentals():
    db = get_db()
    today = date.today()
    upcoming = db.execute(
        "SELECT r.*, v.name, v.image FROM reservations r JOIN vehicles v ON v.id = r.vehicle_id"
        " WHERE r.user_id = ? AND r.status = 'confirmed' AND r.return_date >= ?"
        " ORDER BY r.pickup_date",
        [session["user_id"], today.isoformat()]).fetchall()
    history = rentals.rental_history(db, session["user_id"], today)
    return render_template("rentals.html", upcoming=upcoming, history=history,
                           confirmed=request.args.get("confirmed", type=int))


# ---------- Staff portal ----------

@app.get("/staff")
@login_required("staff")
def dashboard():
    rows = rentals.inventory(get_db(), date.today())
    counts = Counter(r["state"] for r in rows)
    due_today = sum(r["due_today"] for r in rows)

    vtype = request.args.get("type", "")
    state = request.args.get("state", "")
    q = request.args.get("q", "").strip().lower()
    shown = [r for r in rows
             if (not vtype or r["type"] == vtype)
             and (not state or r["state"] == state)
             and (not q or q in r["name"].lower() or q in r["plate"].lower())]
    return render_template("dashboard.html", rows=shown, counts=counts, due_today=due_today,
                           types=rentals.VEHICLE_TYPES, f={"type": vtype, "state": state, "q": q})


@app.get("/staff/fleet")
@login_required("staff")
def fleet():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()
    sql = """SELECT v.*, (SELECT COUNT(*) FROM damage_reports d
                          WHERE d.vehicle_id = v.id AND d.status != 'fixed') AS open_damage
             FROM vehicles v WHERE (v.name LIKE :q OR v.plate LIKE :q)"""
    if show == "active":
        sql += " AND v.status != 'retired'"
    db = get_db()
    vehicles = db.execute(sql + " ORDER BY v.type, v.make, v.model", {"q": f"%{q}%"}).fetchall()

    selected_id = request.args.get("vehicle", type=int)
    selected = next((v for v in vehicles if v["id"] == selected_id), None)
    if selected is None and selected_id:
        # A car hidden by the current filter (e.g. just retired) can still be opened directly.
        selected = db.execute("SELECT v.*, 0 AS open_damage FROM vehicles v WHERE v.id = ?",
                              [selected_id]).fetchone()
    if selected is None and vehicles:
        selected = vehicles[0]
    damage, upcoming = [], []
    if selected:
        damage = db.execute(
            "SELECT * FROM damage_reports WHERE vehicle_id = ? ORDER BY reported_at DESC, id DESC",
            [selected["id"]]).fetchall()
        upcoming = rentals.upcoming_bookings(db, selected["id"], date.today())
    return render_template("fleet.html", vehicles=vehicles, selected=selected, damage=damage,
                           upcoming=upcoming, editing=request.args.get("edit") == "1",
                           f={"show": show, "q": q}, areas=rentals.DAMAGE_AREAS,
                           kinds=rentals.DAMAGE_KINDS, statuses=rentals.DAMAGE_STATUSES,
                           **vehicle_form_options())


def vehicle_form_options():
    return {"types": rentals.VEHICLE_TYPES, "transmissions": rentals.TRANSMISSIONS,
            "fuels": rentals.FUELS, "vehicle_statuses": rentals.VEHICLE_STATUSES,
            "max_year": date.today().year + 1, "min_year": rentals.MIN_YEAR}


def car_photo(make, model):
    """Use a stock photo from static/cars/ if one exists for this make and model."""
    name = f"{make}-{model}".lower().replace(" ", "-") + ".jpg"
    return name if (Path(app.static_folder) / "cars" / name).exists() else None


@app.route("/staff/vehicles/new", methods=["GET", "POST"])
@login_required("staff")
def add_vehicle():
    form = request.form
    if request.method == "POST":
        try:
            v = rentals.parse_vehicle(form, date.today().year)
        except ValueError as e:
            flash(str(e))
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO vehicles (make, model, year, plate, type, seats, daily_rate,"
                    " transmission, fuel, status, image) VALUES (:make, :model, :year, :plate, :type,"
                    " :seats, :daily_rate, :transmission, :fuel, :status, :image)",
                    {**v, "image": car_photo(v["make"], v["model"])})
                db.commit()
            except sqlite3.IntegrityError:
                flash(f"A vehicle with plate {v['plate']} already exists.")
            else:
                flash(f"{v['make']} {v['model']} added to the fleet.", "ok")
                return redirect(url_for("fleet", vehicle=cur.lastrowid))
    return render_template("vehicle_form.html", v=form, **vehicle_form_options())


@app.post("/staff/vehicles/<int:vehicle_id>/edit")
@login_required("staff")
def edit_vehicle(vehicle_id):
    db = get_db()
    car = db.execute("SELECT * FROM vehicles WHERE id = ?", [vehicle_id]).fetchone()
    if car is None:
        abort(404)
    if car["status"] == "retired":
        flash("Retired vehicles can't be edited. Reinstate it first.")
        return redirect(url_for("fleet", vehicle=vehicle_id, show="all"))
    try:
        v = rentals.parse_vehicle(request.form, date.today().year)
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("fleet", vehicle=vehicle_id, edit=1))
    try:
        db.execute(
            "UPDATE vehicles SET make = :make, model = :model, year = :year, plate = :plate, type = :type,"
            " seats = :seats, daily_rate = :daily_rate, transmission = :transmission, fuel = :fuel,"
            " status = :status, image = COALESCE(image, :image) WHERE id = :id",
            {**v, "image": car_photo(v["make"], v["model"]), "id": vehicle_id})
        db.commit()
    except sqlite3.IntegrityError:
        flash(f"A vehicle with plate {v['plate']} already exists.")
        return redirect(url_for("fleet", vehicle=vehicle_id, edit=1))
    flash("Vehicle details saved.", "ok")
    return redirect(url_for("fleet", vehicle=vehicle_id))


@app.post("/staff/vehicles/<int:vehicle_id>/retire")
@login_required("staff")
def retire_vehicle(vehicle_id):
    db = get_db()
    car = db.execute("SELECT * FROM vehicles WHERE id = ?", [vehicle_id]).fetchone()
    if car is None:
        abort(404)
    if request.form.get("action") == "reinstate":
        db.execute("UPDATE vehicles SET status = 'active' WHERE id = ? AND status = 'retired'", [vehicle_id])
        db.commit()
        flash(f"{car['name']} is back in the fleet.", "ok")
        return redirect(url_for("fleet", vehicle=vehicle_id))

    db.execute("BEGIN IMMEDIATE")  # no new booking can sneak in between the check and the update
    booked = rentals.upcoming_bookings(db, vehicle_id, date.today())
    if booked:
        db.rollback()
        flash(f"{car['name']} has {len(booked)} upcoming booking{'s' if len(booked) > 1 else ''}"
              " and can't be retired until they are finished or cancelled.")
        return redirect(url_for("fleet", vehicle=vehicle_id))
    db.execute("UPDATE vehicles SET status = 'retired' WHERE id = ?", [vehicle_id])
    db.commit()
    flash(f"{car['name']} retired. It no longer appears to customers.", "ok")
    return redirect(url_for("fleet", vehicle=vehicle_id, show="all"))


@app.get("/staff/reports")
@login_required("staff")
def reports():
    today = date.today()
    try:
        start = date.fromisoformat(request.args.get("start", ""))
        end = date.fromisoformat(request.args.get("end", ""))
    except ValueError:
        start, end = today - timedelta(days=29), today
    try:
        report = rentals.utilization(get_db(), start, end)
    except ValueError as e:
        flash(str(e))
        start, end = end, start
        report = rentals.utilization(get_db(), start, end)
    return render_template("reports.html", report=report, start=start.isoformat(), end=end.isoformat())


@app.post("/staff/vehicles/<int:vehicle_id>/damage")
@login_required("staff")
def log_damage(vehicle_id):
    form = request.form
    if form.get("area") not in rentals.DAMAGE_AREAS or form.get("kind") not in rentals.DAMAGE_KINDS:
        flash("Pick a damage area and type.")
        return redirect(url_for("fleet", vehicle=vehicle_id))

    db = get_db()
    db.execute(
        "INSERT INTO damage_reports (vehicle_id, area, kind, description, source) VALUES (?, ?, ?, ?, 'staff')",
        [vehicle_id, form["area"], form["kind"], form.get("description", "").strip()[:500]])
    if form.get("out_of_service"):
        db.execute("UPDATE vehicles SET status = 'maintenance' WHERE id = ? AND status = 'active'", [vehicle_id])
    db.commit()
    flash("Damage logged.", "ok")
    return redirect(url_for("fleet", vehicle=vehicle_id))


@app.post("/staff/damage/<int:report_id>/status")
@login_required("staff")
def update_damage(report_id):
    status = request.form.get("status")
    if status not in rentals.DAMAGE_STATUSES:
        abort(400)
    db = get_db()
    report = db.execute("SELECT vehicle_id FROM damage_reports WHERE id = ?", [report_id]).fetchone()
    if report is None:
        abort(404)
    db.execute("UPDATE damage_reports SET status = ? WHERE id = ?", [status, report_id])
    db.commit()
    return redirect(url_for("fleet", vehicle=report["vehicle_id"]))


@app.post("/staff/vehicles/<int:vehicle_id>/service")
@login_required("staff")
def set_service(vehicle_id):
    status = "maintenance" if request.form.get("action") == "out" else "active"
    db = get_db()
    db.execute("UPDATE vehicles SET status = ? WHERE id = ? AND status != 'retired'", [status, vehicle_id])
    db.commit()
    return redirect(url_for("fleet", vehicle=vehicle_id))


if __name__ == "__main__":
    app.run(debug=True)
