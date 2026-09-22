"""
Regression for the admin-panel feature add-ons:
  - Assigned-To filter (list + CSV, admin + agent)
  - 'Activated' status rules (paid-gated, only-transition, terminal)
  - Blank-on-reopen fix (payment persists; legacy 'completed' normalizes to 'paid')
  - Invoice CTA (paid+recon gated, editable, in detail + CSV)
  - Payment-confirmation CC (internal stakeholders CC'd; other emails not)

Run against a LOCAL server (http://127.0.0.1:8000) with the seeded 'gym' DB.
Count-agnostic where possible so it tolerates whatever demo data exists.

    python test_features.py
"""
import sys
import time
import requests
from pymongo import MongoClient
import config
from email_service import email_service, PAYMENT_CONFIRMATION_CC

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0


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


print("=" * 64); print("FEATURE REGRESSION"); print("=" * 64)

admin = login("admin@example.com", "Demo@12345")
check("admin login", admin is not None)

leads = requests.get(f"{BASE}/api/admin/leads", headers=H(admin)).json()["leads"]
# An agent who owns at least one lead (for the filter tests)
owner_email = next((l.get("assigned_to") for l in leads if l.get("assigned_to")), None)

# ---------------------------------------------------------------- Filter
print("\n--- Assigned-To filter ---")
if owner_email:
    r = requests.get(f"{BASE}/api/admin/leads?assigned_to={owner_email}", headers=H(admin)).json()
    check("admin filter -> only that owner's leads",
          r["total"] > 0 and all(l["assigned_to"] == owner_email for l in r["leads"]),
          str({l["lead_id"]: l["assigned_to"] for l in r["leads"]}))
    csv = requests.get(f"{BASE}/api/admin/reports/leads.csv?assigned_to={owner_email}", headers=H(admin)).text
    rows = [l for l in csv.splitlines() if l.strip()][1:]
    check("CSV filtered -> every row is that owner", rows and all(owner_email in r for r in rows), f"{len(rows)} rows")
else:
    check("filter test skipped (no owned leads)", True)

# ---------------------------------------------------------------- Activated status
print("\n--- 'Activated' status rules ---")
pend = [l for l in leads if l.get("payment", {}).get("status") != "paid" and l.get("status") != "activated"]
if len(pend) >= 1:
    lid = pend[0]["lead_id"]
    ref = f"TXN-FEAT-{int(time.time())}"
    r = requests.patch(f"{BASE}/api/admin/leads/{lid}/status", headers=H(admin), data={"status": "activated"})
    check("'activated' blocked before paid -> 400", r.status_code == 400, str(r.status_code))
    r = requests.patch(f"{BASE}/api/admin/leads/{lid}/payment", headers=H(admin),
                       data={"payment_status": "paid", "amount": "5925", "payment_link": ref})
    check("set payment paid -> 200", r.status_code == 200, r.text[:80])
    recon = requests.get(f"{BASE}/api/admin/leads/{lid}", headers=H(admin)).json()["payment"].get("recon_id")
    check("recon id generated", bool(recon), str(recon))
    r = requests.patch(f"{BASE}/api/admin/leads/{lid}/status", headers=H(admin), data={"status": "contacted"})
    check("non-'activated' status after paid -> 400", r.status_code == 400, str(r.status_code))
    r = requests.patch(f"{BASE}/api/admin/leads/{lid}/status", headers=H(admin), data={"status": "activated"})
    check("'activated' allowed after paid -> 200", r.status_code == 200, r.text[:80])
    check("lead.status == activated",
          requests.get(f"{BASE}/api/admin/leads/{lid}", headers=H(admin)).json()["status"] == "activated")
    r = requests.patch(f"{BASE}/api/admin/leads/{lid}/status", headers=H(admin), data={"status": "contacted"})
    check("activated is FINAL (further change -> 400)", r.status_code == 400, str(r.status_code))

    # ----------------------------------------------------- Invoice (uses this paid+recon lead)
    print("\n--- Invoice CTA ---")
    if len(pend) >= 2:
        nid = pend[1]["lead_id"]
        r = requests.post(f"{BASE}/api/admin/leads/{nid}/invoice", headers=H(admin), data={"invoice_number": "X"})
        check("invoice blocked when not paid/recon -> 400", r.status_code == 400, str(r.status_code))
    r = requests.post(f"{BASE}/api/admin/leads/{lid}/invoice", headers=H(admin), data={"invoice_number": "INV-A"})
    check("invoice saved on paid+recon -> 200", r.status_code == 200, r.text[:80])
    check("invoice stored",
          requests.get(f"{BASE}/api/admin/leads/{lid}", headers=H(admin)).json()["payment"].get("invoice_number") == "INV-A")
    r = requests.post(f"{BASE}/api/admin/leads/{lid}/invoice", headers=H(admin), data={"invoice_number": "INV-B"})
    check("invoice editable (overwrite) -> 200", r.status_code == 200)
    check("invoice updated",
          requests.get(f"{BASE}/api/admin/leads/{lid}", headers=H(admin)).json()["payment"].get("invoice_number") == "INV-B")
    csv = requests.get(f"{BASE}/api/admin/reports/leads.csv", headers=H(admin)).text
    check("CSV has 'Invoice Number' header", "Invoice Number" in csv.splitlines()[0])
    check("CSV contains invoice value", "INV-B" in csv)
else:
    check("activated/invoice tests skipped (no pending lead)", True)

# ---------------------------------------------------------------- Blank-fix normalization
print("\n--- Legacy 'completed' normalization ---")
client = MongoClient(config.MONGODB_URL)
db = client[config.MONGODB_DB_NAME]
norm_lead = db.leads.find_one({"payment.status": "pending"})
if norm_lead:
    nlid = norm_lead["lead_id"]
    db.leads.update_one({"lead_id": nlid}, {"$set": {"payment.status": "completed"}})
    api_status = requests.get(f"{BASE}/api/admin/leads/{nlid}", headers=H(admin)).json()["payment"]["status"]
    check("API normalizes 'completed' -> 'paid'", api_status == "paid", api_status)
    db.leads.update_one({"lead_id": nlid}, {"$set": {"payment.status": "pending"}})  # restore
else:
    check("normalization test skipped (no pending lead)", True)

# --------------------- Legacy 'completed' leads are actionable like 'paid' --------------------
# A legacy build stored payment.status='completed'. Display normalizes it to 'paid',
# so the UI offers 'Activated'/Invoice/emails — the write guards MUST accept it too.
print("\n--- Legacy 'completed' is treated as Paid by write guards ---")
leg = db.leads.find_one({"status": {"$nin": ["closed", "activated"]}})
if leg:
    lgid = leg["lead_id"]
    snap = {"status": leg.get("status", "new"), "payment": leg.get("payment", {})}
    db.leads.update_one({"lead_id": lgid}, {"$set": {
        "status": "interested",
        "payment.status": "completed",
        "payment.recon_id": "HHGYM-LEGACY",
    }})
    r = requests.post(f"{BASE}/api/admin/leads/{lgid}/invoice", headers=H(admin), data={"invoice_number": "INV-LEGACY"})
    check("invoice allowed on 'completed' lead -> 200", r.status_code == 200, f"{r.status_code} {r.text[:80]}")
    r = requests.post(f"{BASE}/api/admin/leads/{lgid}/email/payment-confirmation", headers=H(admin))
    check("payment confirmation NOT blocked on 'completed' lead (no 400)", r.status_code != 400, f"{r.status_code} {r.text[:80]}")
    r = requests.patch(f"{BASE}/api/admin/leads/{lgid}/status", headers=H(admin), data={"status": "activated"})
    check("'activated' allowed on 'completed' lead -> 200", r.status_code == 200, f"{r.status_code} {r.text[:80]}")
    db.leads.update_one({"lead_id": lgid}, {"$set": snap})  # restore
else:
    check("legacy-completed test skipped (no eligible lead)", True)
client.close()

# ---------------------------------------------------------------- CC on payment confirmation
print("\n--- Payment-confirmation CC ---")
cap = {}
_orig = email_service._send_email
def _fake(to_email, subject, html, cc=None):
    cap.clear(); cap.update(to=to_email, cc=cc); return {"success": True}
email_service._send_email = _fake
email_service.send_payment_confirmation(customer_email="c@x.com", customer_name="C",
                                        gym_name="Cult", amount=5925, transaction_id="GYM_1", plan_name="3 Months")
check("payment confirmation CC = the stakeholder list", cap.get("cc") == PAYMENT_CONFIRMATION_CC, str(cap.get("cc")))
check("CC list does NOT include someone@example.com", "someone@example.com" not in PAYMENT_CONFIRMATION_CC, str(PAYMENT_CONFIRMATION_CC))
email_service.send_lead_acknowledgement(customer_email="c@x.com", customer_name="C", gym_name="Cult")
check("lead acknowledgement has NO cc", not cap.get("cc"), str(cap.get("cc")))
email_service._send_email = _orig

# ---------------------------------------------------------------- Strict payment-confirmation flow
print("\n--- Payment confirmation requires Paid ---")
fresh = requests.get(f"{BASE}/api/admin/leads", headers=H(admin)).json()["leads"]
unpaid = next((l for l in fresh if l.get("email") and l.get("payment", {}).get("status") != "paid"), None)
if unpaid:
    r = requests.post(f"{BASE}/api/admin/leads/{unpaid['lead_id']}/email/payment-confirmation", headers=H(admin))
    check("payment confirmation blocked when not Paid -> 400", r.status_code == 400, f"{r.status_code} {r.text[:100]}")
else:
    check("strict-flow test skipped (no unpaid lead with email)", True)

print("=" * 64); print(f"RESULT:  {PASS} passed, {FAIL} failed"); print("=" * 64)
sys.exit(1 if FAIL else 0)
