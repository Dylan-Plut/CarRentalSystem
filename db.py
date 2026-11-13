"""SQLite connection handling, schema setup and demo data."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2  # keep in step with the PRAGMA user_version at the end of schema.sql


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def reset_db():
    db = get_db()
    db.executescript(SCHEMA.read_text())
    seed(db)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Drop all tables and reload the demo data."""
        reset_db()
        click.echo("Database reset with demo data.")

    with app.app_context():
        # Build the demo database on first run, and rebuild it if it was made by an older schema.
        if (not Path(app.config["DATABASE"]).exists()
                or get_db().execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION):
            reset_db()


def seed(db):
    db.executemany(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        [
            ("customer@example.com", generate_password_hash("password"), "Alex Morgan", "customer"),
            ("sam@example.com", generate_password_hash("password"), "Sam Lee", "customer"),
            ("staff@example.com", generate_password_hash("password"), "Jordan Patel", "staff"),
        ],
    )
    vehicles = [
        ("Mitsubishi", "Mirage", 2022, "CKRT 214", "Compact", 4, 39, "Automatic", "Gasoline", "active"),
        ("Kia", "Rio", 2023, "CLMB 552", "Compact", 5, 44, "Automatic", "Gasoline", "active"),
        ("Toyota", "Corolla", 2024, "CPDX 318", "Sedan", 5, 55, "Automatic", "Hybrid", "active"),
        ("Honda", "Civic", 2023, "CRWA 907", "Sedan", 5, 58, "Automatic", "Gasoline", "active"),
        ("Nissan", "Sentra", 2019, "BXTE 441", "Sedan", 5, 50, "Automatic", "Gasoline", "retired"),
        ("Toyota", "RAV4", 2024, "CSJK 120", "SUV", 5, 79, "Automatic", "Hybrid", "active"),
        ("Honda", "CR-V", 2023, "CTLP 663", "SUV", 5, 82, "Automatic", "Gasoline", "active"),
        ("Kia", "Sorento", 2022, "CVNE 285", "SUV", 7, 95, "Automatic", "Gasoline", "active"),
        ("Ford", "Explorer", 2023, "CWHB 738", "SUV", 7, 110, "Automatic", "Gasoline", "active"),
        ("Chrysler", "Pacifica", 2022, "CXMR 019", "Van", 7, 105, "Automatic", "Hybrid", "maintenance"),
        ("Toyota", "Sienna", 2024, "CYAF 376", "Van", 8, 115, "Automatic", "Hybrid", "active"),
    ]
    # Photos live in static/cars/, named after the car, e.g. "Honda CR-V" -> honda-cr-v.jpg
    db.executemany(
        "INSERT INTO vehicles (make, model, year, plate, type, seats, daily_rate, transmission, fuel, status, image)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(*v, f"{v[0]}-{v[1]}".lower().replace(" ", "-") + ".jpg") for v in vehicles],
    )

    # Bookings are relative to today so the dashboard, rental history and reports always have data.
    today = date.today()

    def day(offset):
        return (today + timedelta(days=offset)).isoformat()

    branch = "Waterloo – King St N"
    db.executemany(
        "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, branch, extras, total, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # Current and upcoming
            (2, 4, day(-2), day(3), branch, "", 327.70, "confirmed"),    # Civic on rent
            (2, 6, day(-4), day(0), branch, "", 357.08, "confirmed"),    # RAV4 due back today
            (2, 8, day(1), day(5), branch, "", 429.40, "confirmed"),     # Sorento picked up tomorrow
            (2, 3, day(10), day(14), branch, "", 248.60, "confirmed"),   # Corolla later this month
            # Completed rentals (customer@example.com's history + data for the utilization report)
            (1, 3, day(-12), day(-9), branch, "insurance", 237.30, "confirmed"),
            (1, 7, day(-30), day(-26), branch, "", 370.64, "confirmed"),
            (1, 11, day(-58), day(-51), branch, "child_seat", 973.53, "confirmed"),
            (1, 2, day(-75), day(-73), branch, "", 99.44, "confirmed"),
            (1, 9, day(-20), day(-17), branch, "", 372.90, "cancelled"),
            (2, 1, day(-9), day(-6), branch, "", 132.21, "confirmed"),
            (2, 6, day(-25), day(-20), branch, "", 446.35, "confirmed"),
            (2, 8, day(-16), day(-11), branch, "", 536.75, "confirmed"),
            (2, 5, day(-40), day(-35), branch, "", 282.50, "confirmed"),   # Sentra, before it was retired
            (2, 10, day(-22), day(-15), branch, "", 830.55, "confirmed"),
        ],
    )
    db.executemany(
        "INSERT INTO damage_reports (vehicle_id, area, kind, description, source, status, reported_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (6, "Rear bumper", "Scratch", "Light scratch above the plate.", "customer", "needs_review", day(-1)),
            (10, "Driver door", "Dent", "Fist-sized dent, paint intact.", "staff", "repair_booked", day(-6)),
            (10, "Windshield", "Chip", "Small chip, passenger side.", "staff", "fixed", day(-20)),
        ],
    )
