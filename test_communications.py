"""
Regression for the admin-only Communications module:
  - RBAC: every communications endpoint is 403 for agents
  - CC settings: seeded defaults, add/delete, validation, dedupe, instant effect
  - From address: read-only (no write path exists)
  - Communications log: rows written on send with real envelope (from/to/cc),
    grouped-by-lead listing, per-lead timeline, filters
  - Playbook: all 5 types with trigger/conditions merged with live CC
  - Preview: renders the real template with sample data

Run against a LOCAL server (http://127.0.0.1:8000) with the seeded 'gym' DB.
SendGrid is NOT configured locally, so sends are recorded as status='failed'
("SendGrid not configured") — which conveniently also exercises failure logging.

    python test_communications.py
"""
import sys
import time
import requests
from pymongo import MongoClient
import config

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0
ALL_TYPES = ["LEAD_ACKNOWLEDGEMENT", "NO_RESPONSE_FOLLOWUP", "PAYMENT_CONFIRMATION",
             "INTERIM_INFO", "NO_INTEREST_CLOSURE"]


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name}  {extra}")


def login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw})
    return r.json()["access_token"] if r.status_code == 200 else None


def H(t):
    return {"Authorization": f"Bearer {t}"}


print("=" * 64); print("COMMUNICATIONS MODULE REGRESSION"); print("=" * 64)

admin = login("admin@example.com", "Demo@12345")
agent = login("nikhil@example.com", "Demo@12345")
check("admin login", admin is not None)
check("agent login", agent is not None)

client = MongoClient(config.MONGODB_URL)
db = client[config.MONGODB_DB_NAME]

# Snapshot CC settings so the suite restores everything at the end
settings_snap = db.settings.find_one({"_id": "email_cc"})

# ---------------------------------------------------------------- RBAC
print("\n--- RBAC: agents get 403 on every communications endpoint ---")
endpoints = [
    ("GET", "/api/admin/communications"),
    ("GET", "/api/admin/communications/settings"),
    ("GET", "/api/admin/communications/playbook"),
    ("GET", "/api/admin/communications/playbook/PAYMENT_CONFIRMATION/preview"),
    ("GET", "/api/admin/communications/GYM_ANY"),
]
for method, ep in endpoints:
    r = requests.request(method, f"{BASE}{ep}", headers=H(agent))
    check(f"agent {method} {ep} -> 403", r.status_code == 403, str(r.status_code))
r = requests.put(f"{BASE}/api/admin/communications/settings/cc/INTERIM_INFO",
                 headers=H(agent), json={"cc": ["x@y.com"]})
check("agent PUT cc -> 403", r.status_code == 403, str(r.status_code))
r = requests.get(f"{BASE}/api/admin/communications", headers={})
check("unauthenticated -> 401/403", r.status_code in (401, 403), str(r.status_code))

# ---------------------------------------------------------------- Settings
print("\n--- CC settings ---")
r = requests.get(f"{BASE}/api/admin/communications/settings", headers=H(admin))
check("admin GET settings -> 200", r.status_code == 200, str(r.status_code))
st = r.json()
check("from is the system sender", st.get("from_email") == "noreply.healthcare@example.com", str(st.get("from_email")))
check("from is flagged non-editable", st.get("from_editable") is False)
check("all 5 email types present in cc_lists", set(st.get("cc_lists", {}).keys()) == set(ALL_TYPES),
      str(list(st.get("cc_lists", {}).keys())))
check("payment CC seeded with the 2 internal stakeholders",
      set(st["cc_lists"]["PAYMENT_CONFIRMATION"]) == {"ops.one@example.com", "ops.two@example.com"},
      str(st["cc_lists"]["PAYMENT_CONFIRMATION"]))

# add / validate / dedupe / delete
r = requests.put(f"{BASE}/api/admin/communications/settings/cc/INTERIM_INFO",
                 headers=H(admin), json={"cc": ["not-an-email"]})
check("invalid email rejected -> 400", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
r = requests.put(f"{BASE}/api/admin/communications/settings/cc/INTERIM_INFO",
                 headers=H(admin), json={"cc": ["CC.One@example.com", "cc.one@example.com", "cc.two@example.com"]})
check("case-insensitive dedupe on save", r.status_code == 200 and r.json()["cc"] == ["CC.One@example.com", "cc.two@example.com"],
      str(r.json()))
r = requests.put(f"{BASE}/api/admin/communications/settings/cc/BOGUS", headers=H(admin), json={"cc": []})
check("unknown email type -> 400", r.status_code == 400, str(r.status_code))
r = requests.put(f"{BASE}/api/admin/communications/settings/cc/INTERIM_INFO",
                 headers=H(admin), json={"cc": ["a@b.com"] * 1 + [f"u{i}@x.com" for i in range(11)]})
check("more than 10 CCs rejected -> 400", r.status_code == 400, str(r.status_code))
r = requests.get(f"{BASE}/api/admin/communications/settings", headers=H(admin))
check("edit persisted", r.json()["cc_lists"]["INTERIM_INFO"] == ["CC.One@example.com", "cc.two@example.com"],
      str(r.json()["cc_lists"]["INTERIM_INFO"]))
check("no endpoint exists to change From",
      requests.put(f"{BASE}/api/admin/communications/settings/from", headers=H(admin),
                   json={"from_email": "evil@x.com"}).status_code in (404, 405))

# ---------------------------------------------------------------- Playbook + preview
print("\n--- Playbook & preview ---")
r = requests.get(f"{BASE}/api/admin/communications/playbook", headers=H(admin))
pb = {e["email_type"]: e for e in r.json().get("playbook", [])}
check("playbook lists all 5 types", set(pb.keys()) == set(ALL_TYPES), str(list(pb.keys())))
check("ack is auto, rest are manual",
      pb["LEAD_ACKNOWLEDGEMENT"]["trigger"] == "auto" and
      all(pb[t]["trigger"] == "manual" for t in ALL_TYPES if t != "LEAD_ACKNOWLEDGEMENT"))
check("playbook carries live CC (INTERIM_INFO edit visible)",
      pb["INTERIM_INFO"]["cc"] == ["CC.One@example.com", "cc.two@example.com"], str(pb["INTERIM_INFO"]["cc"]))
check("payment card documents the strict Paid condition",
      any("Paid" in c for c in pb["PAYMENT_CONFIRMATION"]["conditions"]))
for t in ALL_TYPES:
    r = requests.get(f"{BASE}/api/admin/communications/playbook/{t}/preview", headers=H(admin))
    ok = r.status_code == 200 and r.json().get("subject") and "Demo Webapp" in r.json().get("html", "")
    check(f"preview renders: {t}", ok, str(r.status_code))
r = requests.get(f"{BASE}/api/admin/communications/playbook/BOGUS/preview", headers=H(admin))
check("preview of unknown type -> 404", r.status_code == 404, str(r.status_code))

# ---------------------------------------------------------------- Log on send
print("\n--- Communications log: rows written on send with the live CC ---")
leads = requests.get(f"{BASE}/api/admin/leads", headers=H(admin)).json()["leads"]
target = next((l for l in leads if l.get("email") and l.get("payment", {}).get("status") == "paid"
               and l.get("status") != "activated"), None)
if target:
    lid = target["lead_id"]
    before = db.communications.count_documents({"lead_id": lid})
    r = requests.post(f"{BASE}/api/admin/leads/{lid}/email/interim-info", headers=H(admin))
    sent_ok = r.status_code == 200
    check("interim-info send accepted", sent_ok, f"{r.status_code} {r.text[:80]}")
    row = db.communications.find_one({"lead_id": lid, "email_type": "INTERIM_INFO"}, sort=[("sent_at", -1)])
    check("log row written", row is not None and db.communications.count_documents({"lead_id": lid}) == before + 1)
    if row:
        check("log row carries the live CC list", row.get("cc") == ["CC.One@example.com", "cc.two@example.com"], str(row.get("cc")))
        check("log row envelope: from/to/subject", row.get("from") == "noreply.healthcare@example.com"
              and row.get("to") == target["email"] and bool(row.get("subject")))
        check("log row trigger=manual, sent_by=admin",
              row.get("trigger") == "manual" and row.get("sent_by") == "admin@example.com",
              f"{row.get('trigger')}/{row.get('sent_by')}")
        check("failed send recorded as status=failed (SendGrid off locally)",
              row.get("status") == "failed" and row.get("error"), str(row.get("status")))

    # grouped list + timeline
    r = requests.get(f"{BASE}/api/admin/communications", headers=H(admin)).json()
    grp = next((g for g in r["leads"] if g["lead_id"] == lid), None)
    check("grouped log has one row for the lead", grp is not None and grp["email_count"] >= 1, str(grp))
    check("grouped row lists INTERIM_INFO in types_sent", grp and "INTERIM_INFO" in grp["types_sent"])
    r = requests.get(f"{BASE}/api/admin/communications/{lid}", headers=H(admin)).json()
    check("timeline returns the send", r["total"] >= 1 and r["communications"][0]["email_type"] == "INTERIM_INFO")
    # filters
    r = requests.get(f"{BASE}/api/admin/communications?email_type=INTERIM_INFO&status=failed", headers=H(admin)).json()
    check("filter by type+status finds it", any(g["lead_id"] == lid for g in r["leads"]))
    r = requests.get(f"{BASE}/api/admin/communications?email_type=PAYMENT_CONFIRMATION&search={lid}", headers=H(admin)).json()
    check("filter by other type excludes it",
          not any("INTERIM_INFO" in g["types_sent"] and set(g["types_sent"]) == {"INTERIM_INFO"} for g in r["leads"])
          or all(lid != g["lead_id"] or "PAYMENT_CONFIRMATION" in g["types_sent"] for g in r["leads"]))
else:
    check("send-log test skipped (no paid lead with email)", True)

# --------------------------------------------------- Auto acknowledgement is logged too
print("\n--- Auto lead-acknowledgement send is logged (trigger=auto) ---")
gym = db.gyms.find_one({"is_active": True}) or db.gyms.find_one({})
if gym:
    payload = {
        "gym_id": gym["gym_id"], "gym_name": gym.get("gym_name", "Test Gym"),
        "partner_name": gym.get("partner_name", "Partner"),
        "full_name": "Comms AutoTest", "phone": "9876500000",
        "email": f"comms.autotest.{int(time.time())}@example.com",
        "preferred_plan": "3 Months", "billing_address": "Test Address, Delhi",
    }
    r = requests.post(f"{BASE}/api/subscription/request", json=payload)
    if r.status_code == 200:
        new_lid = r.json()["lead_id"]
        row = db.communications.find_one({"lead_id": new_lid, "email_type": "LEAD_ACKNOWLEDGEMENT"})
        check("auto ack logged", row is not None)
        if row:
            check("auto ack trigger=auto, sent_by=system",
                  row.get("trigger") == "auto" and row.get("sent_by") == "system",
                  f"{row.get('trigger')}/{row.get('sent_by')}")
            check("auto ack CC empty by default", row.get("cc") == [], str(row.get("cc")))
        # cleanup the synthetic lead + its log rows
        db.leads.delete_one({"lead_id": new_lid})
        db.communications.delete_many({"lead_id": new_lid})
    else:
        check(f"lead submit failed ({r.status_code}) — auto-ack test skipped", False, r.text[:100])
else:
    check("auto-ack test skipped (no gym)", True)

# ---------------------------------------------------------------- Restore settings
if settings_snap:
    db.settings.replace_one({"_id": "email_cc"}, settings_snap, upsert=True)
else:
    db.settings.delete_one({"_id": "email_cc"})
r = requests.get(f"{BASE}/api/admin/communications/settings", headers=H(admin))
check("settings restored to pre-test state",
      set(r.json()["cc_lists"]["PAYMENT_CONFIRMATION"]) == {"ops.one@example.com", "ops.two@example.com"}
      and r.json()["cc_lists"]["INTERIM_INFO"] == (settings_snap or {}).get("cc_lists", {}).get("INTERIM_INFO", []))
client.close()

print("=" * 64); print(f"RESULT:  {PASS} passed, {FAIL} failed"); print("=" * 64)
sys.exit(1 if FAIL else 0)
