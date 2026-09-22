"""
Regression test: date filters must work identically on the leads table
(/api/admin/leads) and the CSV export (/api/admin/reports/leads.csv).

Bug: the table endpoint didn't accept from_date/to_date at all, and the
export treated dates as UTC midnights — "To 22 Jun" excluded almost the
whole of 22 Jun, and dates cut at 05:30 IST because created_at is UTC
while the UI shows IST. Filters must mean IST calendar days, inclusive.
"""
import csv
import io
from datetime import datetime

import requests
from pymongo import MongoClient

import config

BASE = "http://localhost:8000"
db = MongoClient(config.MONGODB_URL)[config.MONGODB_DB_NAME]

passed = failed = 0
def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")

r = requests.post(f"{BASE}/api/auth/login",
                  json={"email": "admin@example.com", "password": "Demo@12345"})
token = r.json().get("access_token")
check("admin login", token is not None)
H = {"Authorization": f"Bearer {token}"}

def table_ids(**params):
    r = requests.get(f"{BASE}/api/admin/leads", headers=H,
                     params={**params, "per_page": 100})
    if r.status_code != 200:
        return r.status_code
    return sorted(l["lead_id"] for l in r.json()["leads"])

def export_ids(**params):
    r = requests.get(f"{BASE}/api/admin/reports/leads.csv", headers=H, params=params)
    if r.status_code != 200:
        return r.status_code
    rows = list(csv.reader(io.StringIO(r.text)))
    return sorted(row[0] for row in rows[1:] if row)

# --- Setup: leads at the edges of one IST calendar day (2026-01-15) --------
# IST = UTC+5:30, so 15 Jan 00:10 IST = 14 Jan 18:40 UTC,
#                    15 Jan 23:50 IST = 15 Jan 18:20 UTC.
BOUNDARY = [
    ("DATETEST_early", datetime(2026, 1, 14, 18, 40)),   # 15 Jan 00:10 IST
    ("DATETEST_late",  datetime(2026, 1, 15, 18, 20)),   # 15 Jan 23:50 IST
    ("DATETEST_before", datetime(2026, 1, 14, 18, 20)),  # 14 Jan 23:50 IST
    ("DATETEST_after",  datetime(2026, 1, 15, 18, 40)),  # 16 Jan 00:10 IST
]
# Build the fixture leads from scratch so the suite runs on a freshly seeded database.
gym = db.gyms.find_one({}, {"gym_id": 1, "gym_name": 1, "partner_name": 1})
for lead_id, created in BOUNDARY:
    db.leads.insert_one({
        "lead_id": lead_id, "created_at": created, "status": "new",
        "gym_id": gym["gym_id"], "gym_name": gym["gym_name"],
        "partner_name": gym.get("partner_name", "Partner"),
        "full_name": lead_id, "phone": "9999900000", "email": "datetest@example.com",
        "preferred_plan": "1 Month", "billing_address": "Test Address",
        "user_location": {"latitude": None, "longitude": None, "city": None},
        "payment": {"status": "pending", "amount": None, "payment_link": None, "updated_at": None},
        "comments": [], "audit_log": [],
    })

try:
    # --- Table must accept and apply date filters --------------------------
    day = {"from_date": "2026-01-15", "to_date": "2026-01-15"}
    t = table_ids(**day)
    check("table filters to the IST day 15 Jan (both edges, nothing else)",
          t == ["DATETEST_early", "DATETEST_late"], f"got {t}")

    # --- Export must return exactly the same rows --------------------------
    e = export_ids(**day)
    check("export matches table for the same day", e == t, f"table={t} export={e}")

    # --- To-date day is inclusive ------------------------------------------
    e = export_ids(from_date="2026-01-01", to_date="2026-01-15")
    check("export includes leads created late on the To day",
          "DATETEST_late" in e and "DATETEST_after" not in e, f"got {e}")

    # --- From-date includes the IST early morning --------------------------
    e = export_ids(from_date="2026-01-15", to_date="2026-01-31")
    check("export includes leads created 00:00-05:30 IST on the From day",
          "DATETEST_early" in e and "DATETEST_before" not in e, f"got {e}")

    # --- Dates combined with another filter stay in parity -----------------
    t = table_ids(status="new", **day)
    e = export_ids(status="new", **day)
    check("status + dates: table == export", t == e and len(t) == 2,
          f"table={t} export={e}")

    # --- Invalid date rejected on both -------------------------------------
    check("table rejects bad date", table_ids(from_date="15-01-2026") == 400)
    check("export rejects bad date", export_ids(from_date="15-01-2026") == 400)
finally:
    db.leads.delete_many({"lead_id": {"$regex": "^DATETEST_"}})

print(f"\nRESULT: {passed} passed, {failed} failed")
exit(1 if failed else 0)
