"""The passcode lock: hashing, first-run setup, sign in/out, lockout, and protection."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from tests import support  # noqa: F401  (lowers the hash rounds for tests)
from finance_tracker import auth
from finance_tracker.store import Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.test_prices import FakeProvider


class HashingTests(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = auth.hash_passcode("135790")
        self.assertNotIn("135790", stored)               # never stored as-is
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(auth.verify_passcode("135790", stored))
        self.assertFalse(auth.verify_passcode("135791", stored))
        self.assertNotEqual(stored, auth.hash_passcode("135790"))  # random salt each time
        self.assertFalse(auth.verify_passcode("135790", "garbage"))

    def test_validation(self):
        self.assertEqual(auth.validate_passcode(" 012345 "), "012345")
        for bad in ["12345", "1234567", "12a456", "", "١٢٣٤٥٦"]:  # last: non-ASCII digits
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    auth.validate_passcode(bad)

    def test_lockout_schedule(self):
        self.assertEqual([auth.lockout_seconds(n) for n in range(4, 9)], [0, 30, 60, 120, 240])
        self.assertEqual(auth.lockout_seconds(50), auth.MAX_LOCKOUT)

    def test_reset_from_the_mac(self):
        with Store(":memory:") as store:
            store.set_passcode_hash(auth.hash_passcode("111111"))
            store.add_session("abc", "phone")
            store.clear_passcode()
            self.assertIsNone(store.passcode_hash())
            self.assertEqual(store.session_count(), 0)


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class LockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "finance.db")
        self.app = create_app(self.db, provider=FakeProvider({}), today=lambda: date(2026, 11, 22), static_dir=None)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def other_device(self):
        return TestClient(self.app)

    def test_everything_is_locked_until_a_passcode_is_set(self):
        self.assertEqual(self.client.get("/api/auth/status").json(), {"passcode_set": False, "signed_in": False})
        for path in ["/api/profile", "/api/transactions", "/api/settings", "/api/transactions.csv"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"passcode": "123456"}).status_code, 409)

    def test_setup_signs_you_in_once(self):
        self.assertEqual(self.client.post("/api/auth/setup", json={"passcode": "12345"}).status_code, 400)
        response = self.client.post("/api/auth/setup", json={"passcode": "246810"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(self.client.get("/api/profile").status_code, 200)
        # A second setup can't replace the passcode.
        self.assertEqual(self.client.post("/api/auth/setup", json={"passcode": "999999"}).status_code, 409)
        with Store(self.db) as store:
            self.assertNotIn("246810", store.passcode_hash())

    def test_sign_in_and_out_on_another_device(self):
        self.client.post("/api/auth/setup", json={"passcode": "246810"})
        with self.other_device() as phone:
            self.assertEqual(phone.get("/api/transactions").status_code, 401)
            wrong = phone.post("/api/auth/login", json={"passcode": "000000"})
            self.assertEqual(wrong.status_code, 401)
            self.assertIn("Wrong passcode", wrong.json()["detail"])
            self.assertEqual(phone.post("/api/auth/login", json={"passcode": "246810"}).status_code, 200)
            self.assertEqual(phone.get("/api/transactions").status_code, 200)
            phone.post("/api/auth/logout")
            self.assertEqual(phone.get("/api/transactions").status_code, 401)
        self.assertEqual(self.client.get("/api/transactions").status_code, 200)  # the Mac is unaffected

    def test_lockout_after_repeated_wrong_guesses(self):
        self.client.post("/api/auth/setup", json={"passcode": "246810"})
        with self.other_device() as attacker:
            codes = [attacker.post("/api/auth/login", json={"passcode": f"00000{i}"}).status_code for i in range(5)]
            self.assertEqual(codes, [401] * 5)
            locked = attacker.post("/api/auth/login", json={"passcode": "246810"})  # even the right one
            self.assertEqual(locked.status_code, 429)
            self.assertIn("Try again in", locked.json()["detail"])
            self.assertIn("retry-after", locked.headers)
        # Once the lock expires, the right passcode works and the counter resets.
        with Store(self.db) as store:
            store.set_auth_failures(5, datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.other_device() as phone:
            self.assertEqual(phone.post("/api/auth/login", json={"passcode": "246810"}).status_code, 200)
        with Store(self.db) as store:
            self.assertEqual(store.auth_failures(), (0, None))

    def test_change_passcode_signs_out_other_devices(self):
        self.client.post("/api/auth/setup", json={"passcode": "246810"})
        phone = self.other_device()
        phone.post("/api/auth/login", json={"passcode": "246810"})
        self.assertEqual(self.client.post("/api/auth/change", json={"current": "111111", "new": "135790"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/change", json={"current": "246810", "new": "13579"}).status_code, 400)
        changed = self.client.post("/api/auth/change", json={"current": "246810", "new": "135790"}).json()
        self.assertEqual(changed, {"changed": True, "signed_out_devices": 1})
        self.assertEqual(self.client.get("/api/profile").status_code, 200)   # this device stays in
        self.assertEqual(phone.get("/api/profile").status_code, 401)        # the other is out
        self.assertEqual(phone.post("/api/auth/login", json={"passcode": "135790"}).status_code, 200)
        phone.close()

    def test_stolen_database_session_hash_is_useless(self):
        self.client.post("/api/auth/setup", json={"passcode": "246810"})
        with Store(self.db) as store:
            stored_hash = store.conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        with self.other_device() as thief:
            thief.cookies.set(auth.COOKIE, stored_hash)  # the hash isn't the token
            self.assertEqual(thief.get("/api/profile").status_code, 401)

    def test_idle_sessions_expire(self):
        self.client.post("/api/auth/setup", json={"passcode": "246810"})
        long_ago = (datetime.now(timezone.utc) - timedelta(days=auth.SESSION_DAYS + 1)).isoformat()
        with Store(self.db) as store:
            store.conn.execute("UPDATE sessions SET last_seen = ?", (long_ago,))
            store.conn.commit()
        self.assertEqual(self.client.get("/api/profile").status_code, 401)


if __name__ == "__main__":
    unittest.main()
