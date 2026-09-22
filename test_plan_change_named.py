"""
Regression test: plan change must accept the gym's NAMED plans (stored in
gym.plans), not just the 4 legacy duration labels.

Bug: PATCH /api/admin/leads/{id}/plan validated against
gym.subscription_plans_list — a field computed only in the /api/gyms/{id}
response and stored on 0 of 1722 gym docs — so every named plan was
rejected with "not available for this gym".
"""
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

def login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw})
    return r.json().get("access_token") if r.status_code == 200 else None

token = login("admin@example.com", "Demo@12345")
check("admin login", token is not None)
H = {"Authorization": f"Bearer {token}"}

# --- Setup: an unpaid lead on a gym with named plans -----------------------
gym = db.gyms.find_one({"plans.1": {"$exists": True}, "is_active": True},
                       {"gym_id": 1, "gym_name": 1, "partner_name": 1, "plans": 1})
check("found a named-plans gym", gym is not None)
plan_names = [p["plan_name"] for p in gym["plans"]]
first_plan, second_plan = plan_names[0], plan_names[1]

r = requests.post(f"{BASE}/api/subscription/request", json={
    "gym_id": gym["gym_id"], "gym_name": gym["gym_name"],
    "partner_name": gym.get("partner_name", "Partner"),
    "full_name": "Plan Change Test", "phone": "9999900001",
    "email": "planchange.test@example.com",
    "preferred_plan": first_plan, "billing_address": "Test Address, Noida",
})
check("test lead created", r.status_code == 200, r.text[:200])
lead_id = r.json().get("lead_id")

try:
    # --- The bug: upsell to another NAMED plan must succeed ----------------
    r = requests.patch(f"{BASE}/api/admin/leads/{lead_id}/plan", headers=H,
                       data={"new_plan": second_plan, "reason": "upsold on call"})
    check(f"change to named plan '{second_plan}' accepted", r.status_code == 200, r.text[:200])

    lead = db.leads.find_one({"lead_id": lead_id})
    check("lead now stores the new plan", lead.get("preferred_plan") == second_plan,
          f"got {lead.get('preferred_plan')}")

    # --- Guard rails must still hold ---------------------------------------
    r = requests.patch(f"{BASE}/api/admin/leads/{lead_id}/plan", headers=H,
                       data={"new_plan": "12 Months"})
    check("generic duration label rejected on named-plans gym", r.status_code == 400, r.text[:200])

    r = requests.patch(f"{BASE}/api/admin/leads/{lead_id}/plan", headers=H,
                       data={"new_plan": "Totally Fake Plan"})
    check("unknown plan still rejected", r.status_code == 400, r.text[:200])

    db.leads.update_one({"lead_id": lead_id},
                        {"$set": {"payment.status": "paid", "payment.amount": 5925}})
    r = requests.patch(f"{BASE}/api/admin/leads/{lead_id}/plan", headers=H,
                       data={"new_plan": first_plan})
    check("plan locked after paid", r.status_code == 400, r.text[:200])
finally:
    db.leads.delete_one({"lead_id": lead_id})
    db.communications.delete_many({"lead_id": lead_id})

print(f"\nRESULT: {passed} passed, {failed} failed")
exit(1 if failed else 0)
