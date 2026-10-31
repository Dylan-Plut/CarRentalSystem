DROP TABLE IF EXISTS damage_reports;
DROP TABLE IF EXISTS reservations;
DROP TABLE IF EXISTS vehicles;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('customer', 'staff'))
);

CREATE TABLE vehicles (
    id           INTEGER PRIMARY KEY,
    model        TEXT NOT NULL,
    plate        TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL CHECK (type IN ('Compact', 'Sedan', 'SUV', 'Van')),
    seats        INTEGER NOT NULL,
    daily_rate   REAL NOT NULL,
    transmission TEXT NOT NULL,
    fuel         TEXT NOT NULL,
    image        TEXT,  -- file name under static/cars/
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'retired'))
);

-- A booking holds the car from pickup_date up to (and including the morning of) return_date,
-- so one rental can end on the same day the next one starts.
CREATE TABLE reservations (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    pickup_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    branch      TEXT NOT NULL,
    extras      TEXT NOT NULL DEFAULT '',
    total       REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (return_date > pickup_date)
);

CREATE TABLE damage_reports (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    area        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL CHECK (source IN ('staff', 'customer')),
    status      TEXT NOT NULL DEFAULT 'needs_review' CHECK (status IN ('needs_review', 'repair_booked', 'fixed')),
    reported_at TEXT NOT NULL DEFAULT (date('now', 'localtime'))
);

CREATE INDEX idx_reservations_vehicle ON reservations(vehicle_id, pickup_date, return_date);
