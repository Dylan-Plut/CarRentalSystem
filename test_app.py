"""Sprint 02 tests: rental history, fleet management (incl. damage records) and the utilization report.

Run with:  python -m unittest -v
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

DB_FILE = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE"] = DB_FILE

import app as app_module  # noqa: E402  (DATABASE must be set first)
import db as database  # noqa: E402
import rentals  # noqa: E402

TODAY = date.today()


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.app = app_module.app
        self.app.config["TESTING"] = True
        with self.app.app_context():
            database.reset_db()
        self.client = self.app.test_client()

    def login(self, email):
        return self.client.post("/login", data={"email": email, "password": "password"})

    def query(self, sql, params=()):
        with self.app.app_context():
            return database.get_db().execute(sql, params).fetchall()


class RentalHistoryTests(BaseCase):
    def test_history_only_has_this_customers_past_rentals_newest_first(self):
        with self.app.app_context():
            rows = rentals.rental_history(database.get_db(), 1, TODAY)
        self.assertTrue(rows)
        user_ids = {r[0] for r in self.query(
            "SELECT user_id FROM reservations WHERE id IN (%s)" % ",".join(str(r["id"]) for r in rows))}
        self.assertEqual(user_ids, {1})
        self.assertTrue(all(r["return_date"] < TODAY.isoformat() or r["status"] == "cancelled" for r in rows))
        pickups = [r["pickup_date"] for r in rows]
        self.assertEqual(pickups, sorted(pickups, reverse=True))

    def test_history_includes_duration_vehicle_and_cost(self):
        with self.app.app_context():
            r = rentals.rental_history(database.get_db(), 1, TODAY)[0]
        for key in ("id", "name", "year", "pickup_date", "return_date", "days", "total"):
            self.assertIn(key, r)
        self.assertEqual(r["days"], (date.fromisoformat(r["return_date"])
                                     - date.fromisoformat(r["pickup_date"])).days)

    def test_history_page_shows_own_rentals(self):
        self.login("customer@example.com")
        page = self.client.get("/rentals").get_data(as_text=True)
        self.assertIn("Rental history", page)
        self.assertIn("Toyota Sienna", page)  # one of Alex's past rentals
        self.assertNotIn("Kia Sorento", page)  # Sam's rental, must not leak

    def test_history_requires_login(self):
        self.assertEqual(self.client.get("/rentals").status_code, 302)


class FleetManagementTests(BaseCase):
    NEW_CAR = {"make": "Hyundai", "model": "Elantra", "year": "2024", "plate": "dfgh 101", "type": "Sedan",
               "seats": "5", "daily_rate": "52.50", "transmission": "Automatic", "fuel": "Gasoline",
               "status": "active"}

    def setUp(self):
        super().setUp()
        self.login("staff@example.com")

    def test_add_vehicle_appears_to_customers(self):
        resp = self.client.post("/staff/vehicles/new", data=self.NEW_CAR)
        self.assertEqual(resp.status_code, 302)
        row = self.query("SELECT * FROM vehicles WHERE plate = 'DFGH 101'")[0]
        self.assertEqual((row["name"], row["year"], row["seats"], row["daily_rate"]), ("Hyundai Elantra", 2024, 5, 52.5))
        with self.app.app_context():
            ids = [c["id"] for c in rentals.search_vehicles(database.get_db(), TODAY + timedelta(days=1),
                                                            TODAY + timedelta(days=2))]
        self.assertIn(row["id"], ids)

    def test_add_vehicle_rejects_bad_input_and_duplicate_plate(self):
        self.client.post("/staff/vehicles/new", data={**self.NEW_CAR, "seats": "0"})
        self.client.post("/staff/vehicles/new", data={**self.NEW_CAR, "plate": "CPDX 318"})  # Corolla's plate
        self.assertEqual(self.query("SELECT COUNT(*) FROM vehicles WHERE make = 'Hyundai'")[0][0], 0)

    def test_edit_vehicle_saves_changes(self):
        data = {**self.NEW_CAR, "make": "Toyota", "model": "Corolla", "plate": "CPDX 318", "daily_rate": "60"}
        self.client.post("/staff/vehicles/3/edit", data=data)
        row = self.query("SELECT * FROM vehicles WHERE id = 3")[0]
        self.assertEqual((row["daily_rate"], row["year"]), (60, 2024))

    def test_retire_vehicle_hides_it_from_customers(self):
        self.client.post("/staff/vehicles/2/retire", data={"action": "retire"})  # Kia Rio, no bookings
        self.assertEqual(self.query("SELECT status FROM vehicles WHERE id = 2")[0][0], "retired")
        self.login("customer@example.com")
        self.assertEqual(self.client.get(f"/vehicles/2?pickup={day(1)}&dropoff={day(2)}").status_code, 404)

    def test_cannot_retire_vehicle_with_upcoming_booking(self):
        self.client.post("/staff/vehicles/8/retire", data={"action": "retire"})  # Sorento booked tomorrow
        self.assertEqual(self.query("SELECT status FROM vehicles WHERE id = 8")[0][0], "active")

    def test_damage_records_are_created_and_retrieved_for_correct_vehicle(self):
        self.client.post("/staff/vehicles/2/damage", data={"area": "Hood", "kind": "Dent", "description": "Hail"})
        rows = self.query("SELECT vehicle_id, area, kind FROM damage_reports WHERE description = 'Hail'")
        self.assertEqual([tuple(r) for r in rows], [(2, "Hood", "Dent")])
        page = self.client.get("/staff/fleet?vehicle=2").get_data(as_text=True)
        self.assertIn("Hail", page)
        self.assertNotIn("Hail", self.client.get("/staff/fleet?vehicle=3").get_data(as_text=True))

    def test_customers_cannot_manage_fleet(self):
        self.login("customer@example.com")
        self.client.post("/staff/vehicles/new", data=self.NEW_CAR)
        self.assertEqual(self.query("SELECT COUNT(*) FROM vehicles WHERE make = 'Hyundai'")[0][0], 0)


class UtilizationReportTests(BaseCase):
    def test_overlap_days_clips_to_range(self):
        d = date(2026, 1, 10)
        self.assertEqual(rentals.overlap_days(d, d + timedelta(days=5), d, d + timedelta(days=9)), 5)
        self.assertEqual(rentals.overlap_days(d - timedelta(days=3), d + timedelta(days=2), d, d + timedelta(days=9)), 2)
        self.assertEqual(rentals.overlap_days(d + timedelta(days=8), d + timedelta(days=20), d, d + timedelta(days=9)), 2)
        self.assertEqual(rentals.overlap_days(d - timedelta(days=5), d, d, d + timedelta(days=9)), 0)

    def test_report_counts_match_hand_calculation(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM reservations")
            db.executemany(
                "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, branch, total, status)"
                " VALUES (1, ?, ?, ?, 'x', 0, ?)",
                [(6, "2026-03-01", "2026-03-05", "confirmed"),   # SUV, 4 days in range
                 (7, "2026-02-27", "2026-03-03", "confirmed"),   # SUV, 2 days in range (Mar 1-2)
                 (3, "2026-03-09", "2026-03-15", "confirmed"),   # Sedan, 2 days in range (Mar 9-10)
                 (4, "2026-03-02", "2026-03-04", "cancelled"),   # ignored
                 (11, "2026-04-01", "2026-04-03", "confirmed")])  # outside range
            db.commit()
            report = rentals.utilization(db, date(2026, 3, 1), date(2026, 3, 10))
        by_type = {r["type"]: r for r in report["rows"]}
        self.assertEqual(report["range_days"], 10)
        self.assertEqual((by_type["SUV"]["rentals"], by_type["SUV"]["rental_days"], by_type["SUV"]["fleet"]), (2, 6, 4))
        self.assertEqual(by_type["SUV"]["utilization"], 15.0)  # 6 / (4 cars * 10 days)
        self.assertEqual(by_type["SUV"]["avg_length"], 4.0)
        self.assertEqual((by_type["Sedan"]["rentals"], by_type["Sedan"]["rental_days"], by_type["Sedan"]["fleet"]), (1, 2, 2))
        self.assertEqual(by_type["Van"]["rentals"], 0)
        self.assertEqual(report["totals"]["rentals"], 3)

    def test_rejects_reversed_range(self):
        with self.app.app_context(), self.assertRaises(ValueError):
            rentals.utilization(database.get_db(), date(2026, 3, 10), date(2026, 3, 1))

    def test_report_page(self):
        self.login("staff@example.com")
        page = self.client.get(f"/staff/reports?start={day(-60)}&end={day(0)}").get_data(as_text=True)
        self.assertIn("Vehicle utilization report", page)
        self.assertIn("SUV", page)
        self.login("customer@example.com")
        self.assertEqual(self.client.get("/staff/reports").status_code, 302)


if __name__ == "__main__":
    unittest.main()
