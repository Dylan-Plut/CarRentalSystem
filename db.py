"""SQLite connection handling, schema setup and demo data."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = Path(__file__).with_name("schema.sql")


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

    if not Path(app.config["DATABASE"]).exists():
        with app.app_context():
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
    db.executemany(
        "INSERT INTO vehicles (model, plate, type, seats, daily_rate, transmission, fuel, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("Mitsubishi Mirage", "CKRT 214", "Compact", 4, 39, "Automatic", "Gasoline", "active"),
            ("Kia Rio", "CLMB 552", "Compact", 5, 44, "Automatic", "Gasoline", "active"),
            ("Toyota Corolla", "CPDX 318", "Sedan", 5, 55, "Automatic", "Hybrid", "active"),
            ("Honda Civic", "CRWA 907", "Sedan", 5, 58, "Automatic", "Gasoline", "active"),
            ("Nissan Sentra", "BXTE 441", "Sedan", 5, 50, "Automatic", "Gasoline", "retired"),
            ("Toyota RAV4", "CSJK 120", "SUV", 5, 79, "Automatic", "Hybrid", "active"),
            ("Honda CR-V", "CTLP 663", "SUV", 5, 82, "Automatic", "Gasoline", "active"),
            ("Kia Sorento", "CVNE 285", "SUV", 7, 95, "Automatic", "Gasoline", "active"),
            ("Ford Explorer", "CWHB 738", "SUV", 7, 110, "Automatic", "Gasoline", "active"),
            ("Chrysler Pacifica", "CXMR 019", "Van", 7, 105, "Automatic", "Hybrid", "maintenance"),
            ("Toyota Sienna", "CYAF 376", "Van", 8, 115, "Automatic", "Hybrid", "active"),
        ],
    )

    # Bookings are relative to today so the dashboard always has something to show.
    today = date.today()

    def day(offset):
        return (today + timedelta(days=offset)).isoformat()

    db.executemany(
        "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, branch, total)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (2, 4, day(-2), day(3), "Waterloo – King St N", 327.70),   # Civic on rent
            (2, 6, day(-4), day(0), "Waterloo – King St N", 357.08),   # RAV4 due back today
            (2, 8, day(1), day(5), "Waterloo – King St N", 429.40),    # Sorento picked up tomorrow
            (2, 3, day(10), day(14), "Waterloo – King St N", 248.60),  # Corolla later this month
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
