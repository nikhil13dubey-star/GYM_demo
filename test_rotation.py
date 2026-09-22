"""
Deterministic, in-process test for round-robin lead assignment.

Runs the REAL DB-layer methods (pick_next_assignee, save_lead,
reassign_open_leads_from_agent) against an ISOLATED throwaway database so the
result does not depend on the messy local 'gym' dev data. No server needed.

    python test_rotation.py
"""

import asyncio
import sys
from datetime import datetime, timedelta

# Point the whole app at a throwaway DB BEFORE anything connects.
import config
config.MONGODB_DB_NAME = "gym_rotation_test"

from mongodb import MongoDB
from mongo_database import MongoLeadManager

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


async def seed_user(db, email, role, active=True, created_offset=0):
    await db.users.insert_one({
        "email": email,
        "name": email.split("@")[0],
        "role": role,
        "is_active": active,
        "created_at": datetime(2024, 1, 1) + timedelta(minutes=created_offset),
    })


async def seed_lead(db, lead_id, owner, status, pay_status):
    await db.leads.insert_one({
        "lead_id": lead_id,
        "created_at": datetime.utcnow(),
        "assigned_to": owner,
        "assigned_to_name": owner.split("@")[0],
        "status": status,
        "payment": {"status": pay_status},
        "audit_log": [],
    })


async def main():
    lm = MongoLeadManager()
    await lm.initialize()
    db = MongoDB.db

    # Clean slate
    await db.users.delete_many({})
    await db.leads.delete_many({})
    await db.counters.delete_many({})

    print("=" * 64)
    print("ROUND-ROBIN ASSIGNMENT TEST  (db: gym_rotation_test)")
    print("=" * 64)

    # Seed: 1 admin (oldest), 3 agents A,B,C in created order
    await seed_user(db, "admin@t.com", "admin", created_offset=0)
    await seed_user(db, "a@t.com", "agent", created_offset=1)
    await seed_user(db, "b@t.com", "agent", created_offset=2)
    await seed_user(db, "c@t.com", "agent", created_offset=3)

    # --- 1. Round-robin cycles A,B,C,A,B,C ---
    picks = []
    for _ in range(6):
        picks.append((await lm.pick_next_assignee())["email"])
    expected = ["a@t.com", "b@t.com", "c@t.com", "a@t.com", "b@t.com", "c@t.com"]
    check("round-robin cycles A,B,C,A,B,C", picks == expected, str(picks))

    # --- 2. save_lead auto-assigns + writes 'auto_assigned' audit entry ---
    lead_id = await lm.save_lead(
        {
            "gym_id": 1, "gym_name": "G", "partner_name": "Cult", "full_name": "Test",
            "phone": "9999999999", "preferred_plan": "1 Month",
        },
        assignee={"email": "b@t.com", "name": "b", "via": "round_robin"},
    )
    saved = await db.leads.find_one({"lead_id": lead_id})
    check("save_lead sets assigned_to", saved.get("assigned_to") == "b@t.com", saved.get("assigned_to"))
    audit = saved.get("audit_log", [])
    check("save_lead writes auto_assigned audit entry",
          any(a.get("action") == "auto_assigned" and a.get("new_value") == "b@t.com" for a in audit),
          str(audit))

    # --- 3. Admin fallback when no active agents ---
    await db.users.update_many({"role": "agent"}, {"$set": {"is_active": False}})
    fb = await lm.pick_next_assignee()
    check("no active agents -> admin fallback email", fb["email"] == "admin@t.com", str(fb))
    check("fallback tagged via=admin_fallback", fb["via"] == "admin_fallback", str(fb))

    # --- 4. Deactivation redistributes OPEN leads, retains closed/paid ---
    # Re-activate B and C (A stays deactivated = the one being removed)
    await db.users.update_many({"email": {"$in": ["b@t.com", "c@t.com"]}}, {"$set": {"is_active": True}})
    # A holds: 2 open, 1 closed, 1 paid
    await seed_lead(db, "L1", "a@t.com", "new", "pending")          # open
    await seed_lead(db, "L2", "a@t.com", "contacted", "link_shared")  # open
    await seed_lead(db, "L3", "a@t.com", "closed", "pending")        # retained (closed)
    await seed_lead(db, "L4", "a@t.com", "interested", "paid")       # retained (paid)

    res = await lm.reassign_open_leads_from_agent("a@t.com", "admin@t.com")
    check("deactivate reassigns exactly the 2 open leads", res["reassigned"] == 2, str(res))

    l1 = await db.leads.find_one({"lead_id": "L1"})
    l2 = await db.leads.find_one({"lead_id": "L2"})
    l3 = await db.leads.find_one({"lead_id": "L3"})
    l4 = await db.leads.find_one({"lead_id": "L4"})
    check("open lead L1 moved off A to an active agent", l1["assigned_to"] in {"b@t.com", "c@t.com"}, l1["assigned_to"])
    check("open lead L2 moved off A to an active agent", l2["assigned_to"] in {"b@t.com", "c@t.com"}, l2["assigned_to"])
    check("closed lead L3 stays attributed to A", l3["assigned_to"] == "a@t.com", l3["assigned_to"])
    check("paid lead L4 stays attributed to A", l4["assigned_to"] == "a@t.com", l4["assigned_to"])
    check("reassign writes reassigned_on_deactivate audit on L1",
          any(a.get("action") == "reassigned_on_deactivate" for a in l1.get("audit_log", [])),
          str(l1.get("audit_log")))

    # --- 5. Reactivated agent rejoins rotation ---
    await db.users.update_one({"email": "a@t.com"}, {"$set": {"is_active": True}})
    seen = set()
    for _ in range(6):
        seen.add((await lm.pick_next_assignee())["email"])
    check("reactivated agent A rejoins rotation", "a@t.com" in seen, str(seen))

    # Cleanup
    await db.users.delete_many({})
    await db.leads.delete_many({})
    await db.counters.delete_many({})
    await MongoDB.client.drop_database("gym_rotation_test")
    await MongoDB.close_db()

    print("=" * 64)
    print(f"RESULT:  {PASS} passed, {FAIL} failed")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
