"""
RBAC + ownership regression test for the agent/admin model.
Run against a LOCAL server (http://127.0.0.1:8000) with the seeded 'gym' DB.
"""
import requests, sys

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
    if r.status_code != 200:
        return None
    return r.json()["access_token"]

def H(tok):
    return {"Authorization": f"Bearer {tok}"}

print("="*64); print("RBAC / OWNERSHIP TEST"); print("="*64)

# --- Admin login ---
admin = login("admin@example.com", "Demo@12345")
check("admin login", admin is not None)

# --- Role vocabulary: agent allowed, legacy roles rejected ---
import time
suffix = str(int(time.time()))
a1_email = f"agent1_{suffix}@example.com"
a2_email = f"agent2_{suffix}@example.com"

def create_user(email, role, pw="Demo@12345"):
    return requests.post(f"{BASE}/api/admin/users", headers=H(admin),
                         data={"email": email, "name": email.split("@")[0], "password": pw, "role": role})

r = create_user(a1_email, "agent");  check("admin creates agent1 (role=agent)", r.status_code == 200, r.text[:120])
r = create_user(a2_email, "agent");  check("admin creates agent2 (role=agent)", r.status_code == 200, r.text[:120])
r = create_user(f"legacy_{suffix}@x.com", "facilitator")
check("legacy role 'facilitator' rejected (400)", r.status_code == 400, f"got {r.status_code}")
r = create_user(f"legacy2_{suffix}@x.com", "viewer")
check("legacy role 'viewer' rejected (400)", r.status_code == 400, f"got {r.status_code}")

agent1 = login(a1_email, "Demo@12345"); check("agent1 login", agent1 is not None)
agent2 = login(a2_email, "Demo@12345"); check("agent2 login", agent2 is not None)

# --- Create two leads via public endpoint ---
def make_lead(name):
    payload = {"gym_id": 1, "gym_name": "Cult Fit Andheri West", "partner_name": "Cult",
               "full_name": name, "email": f"{name.lower()}@example.com", "phone": "9876543210",
               "preferred_plan": "1 Month", "billing_address": "Addr, MH - 400053", "message": ""}
    r = requests.post(f"{BASE}/api/subscription/request", json=payload)
    return r.json().get("lead_id") if r.status_code == 200 else None

lead_a = make_lead("OwnerTestA"); check("create lead A", lead_a is not None, str(lead_a))
lead_b = make_lead("OwnerTestB"); check("create lead B", lead_b is not None, str(lead_b))

# --- New model: leads are AUTO-ASSIGNED at creation (round-robin), NOT claimed on view ---
r = requests.get(f"{BASE}/api/admin/leads/{lead_a}", headers=H(admin))
check("lead A auto-assigned at creation", bool(r.json().get("assigned_to")), r.json().get("assigned_to"))

# Viewing (by admin OR agent) must NOT change the owner — claim-on-open is retired
o1 = requests.get(f"{BASE}/api/admin/leads/{lead_b}", headers=H(admin)).json().get("assigned_to")
requests.get(f"{BASE}/api/admin/leads/{lead_b}", headers=H(agent1))  # agent peeks; must not claim
o2 = requests.get(f"{BASE}/api/admin/leads/{lead_b}", headers=H(admin)).json().get("assigned_to")
check("viewing does NOT change ownership (no claim-on-open)", o1 == o2, f"{o1} != {o2}")

# Deterministic ownership for the tests below: admin assigns lead A -> agent1
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/assign", headers=H(admin), data={"assignee_email": a1_email})
check("admin assigns lead A -> agent1 (200)", r.status_code == 200, r.text[:120])

# --- agent2 cannot modify lead_a (owned by agent1) ---
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/status", headers=H(agent2), data={"status": "contacted"})
check("agent2 status-update on agent1's lead -> 403", r.status_code == 403, f"got {r.status_code}")
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/payment", headers=H(agent2), data={"payment_status": "link_shared"})
check("agent2 payment-update on agent1's lead -> 403", r.status_code == 403, f"got {r.status_code}")

# --- agent1 CAN modify own lead_a ---
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/status", headers=H(agent1), data={"status": "contacted"})
check("agent1 status-update on own lead -> 200", r.status_code == 200, f"got {r.status_code}")
r = requests.post(f"{BASE}/api/admin/leads/{lead_a}/comments", headers=H(agent1), data={"comment": "called customer"})
check("agent1 add comment on own lead -> 200", r.status_code == 200, f"got {r.status_code}")

# --- admin can modify ANY lead ---
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/status", headers=H(admin), data={"status": "interested"})
check("admin status-update on agent1's lead -> 200", r.status_code == 200, f"got {r.status_code}")

# --- Audit log: agent forbidden, admin allowed ---
r = requests.get(f"{BASE}/api/admin/leads/{lead_a}/audit", headers=H(agent1))
check("agent audit view -> 403", r.status_code == 403, f"got {r.status_code}")
r = requests.get(f"{BASE}/api/admin/leads/{lead_a}/audit", headers=H(admin))
check("admin audit view -> 200", r.status_code == 200, f"got {r.status_code}")

# --- Gym add/delete: agent forbidden, admin allowed ---
new_gym = {"gym_name": "RBAC Test Gym", "partner_name": "Cult", "address": "X", "city": "Mumbai",
           "state": "MH", "pincode": "400001", "latitude": 19.0, "longitude": 72.8,
           "amenities": ["Cardio"], "subscription_amount": 1499}
r = requests.post(f"{BASE}/api/admin/gyms", headers=H(agent1), json=new_gym)
check("agent add gym -> 403", r.status_code == 403, f"got {r.status_code}")
r = requests.post(f"{BASE}/api/admin/gyms", headers=H(admin), json=new_gym)
check("admin add gym -> 200", r.status_code == 200, f"got {r.status_code}")
gid = r.json().get("gym_id")
r = requests.delete(f"{BASE}/api/admin/gyms/{gid}", headers=H(agent1))
check("agent delete gym -> 403", r.status_code == 403, f"got {r.status_code}")
r = requests.delete(f"{BASE}/api/admin/gyms/{gid}", headers=H(admin))
check("admin delete gym -> 200", r.status_code == 200, f"got {r.status_code}")

# --- User management & delete: agent forbidden ---
r = requests.get(f"{BASE}/api/admin/users", headers=H(agent1))
check("agent list users -> 403", r.status_code == 403, f"got {r.status_code}")
r = create_user(f"x_{suffix}@x.com", "agent")  # admin works (sanity, already tested)

# --- Admin reassign lead_a to agent2; ownership flips ---
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/assign", headers=H(admin), data={"assignee_email": a2_email})
check("admin reassign lead A -> agent2 (200)", r.status_code == 200, r.text[:120])
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/status", headers=H(agent2), data={"status": "contacted"})
check("agent2 can now act on reassigned lead -> 200", r.status_code == 200, f"got {r.status_code}")
r = requests.patch(f"{BASE}/api/admin/leads/{lead_a}/status", headers=H(agent1), data={"status": "new"})
check("agent1 can NO LONGER act after reassign -> 403", r.status_code == 403, f"got {r.status_code}")

# --- New endpoints: deactivate redistributes open leads; activate restores login ---
a3_email = f"agent3_{suffix}@example.com"
r = create_user(a3_email, "agent"); check("admin creates agent3 (role=agent)", r.status_code == 200, r.text[:120])
users = requests.get(f"{BASE}/api/admin/users", headers=H(admin)).json().get("users", [])
a3 = next((u for u in users if u["email"] == a3_email), None)
check("agent3 listed by admin", a3 is not None)
lead_c = make_lead("OwnerTestC"); check("create lead C", lead_c is not None, str(lead_c))
requests.patch(f"{BASE}/api/admin/leads/{lead_c}/assign", headers=H(admin), data={"assignee_email": a3_email})
check("agent3 can login before deactivate", login(a3_email, "Demo@12345") is not None)
r = requests.delete(f"{BASE}/api/admin/users/{a3['user_id']}", headers=H(admin))
check("deactivate agent3 -> 200", r.status_code == 200, r.text[:120])
check("deactivate reports >=1 lead reassigned", r.json().get("leads_reassigned", 0) >= 1, r.text[:160])
owner_now = requests.get(f"{BASE}/api/admin/leads/{lead_c}", headers=H(admin)).json().get("assigned_to")
check("agent3's open lead moved off agent3", bool(owner_now) and owner_now != a3_email, str(owner_now))
check("deactivated agent3 cannot login (403)", login(a3_email, "Demo@12345") is None)
r = requests.post(f"{BASE}/api/admin/users/{a3['user_id']}/activate", headers=H(admin))
check("activate agent3 -> 200", r.status_code == 200, r.text[:120])
check("reactivated agent3 can login again", login(a3_email, "Demo@12345") is not None)

# --- CSV: agent stripped (no audit cols), admin full ---
r_admin = requests.get(f"{BASE}/api/admin/reports/leads.csv", headers=H(admin))
r_agent = requests.get(f"{BASE}/api/admin/reports/leads.csv", headers=H(agent1))
admin_hdr = r_admin.text.splitlines()[0]
agent_hdr = r_agent.text.splitlines()[0]
check("admin CSV includes audit columns", "All Comments" in admin_hdr and "Latest Status Update" in admin_hdr, admin_hdr)
check("agent CSV excludes audit columns", "All Comments" not in agent_hdr and "Latest Status Update" not in agent_hdr, agent_hdr)
check("agent CSV still has core columns", "Lead ID" in agent_hdr and "Payment Status" in agent_hdr, agent_hdr)

print("="*64); print(f"RESULT:  {PASS} passed, {FAIL} failed"); print("="*64)
sys.exit(1 if FAIL else 0)
