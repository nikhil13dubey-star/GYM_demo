"""
One-time backlog migration: assign existing UNASSIGNED leads to an admin.

Going forward every new lead auto-assigns by round-robin, but leads created
before this change have no owner. This relabels each lead with no `assigned_to`
to the oldest active admin, recording a 'backfill_assigned_to_admin' audit entry.
Already-owned leads are left untouched. Idempotent -- safe to run multiple times.

NOTE: admins are NOT ownership-locked, so admins can already act on unassigned
leads. This migration is mainly cosmetic (the UI shows the admin as owner
instead of "Unassigned").

Usage:
    python migrate_unassigned_leads_to_admin.py            # migrate
    python migrate_unassigned_leads_to_admin.py --dry-run  # show changes, no writes

Run against the SAME MONGODB_URL / MONGODB_DB_NAME the app uses (set via .env
or environment). For prod, point it at the Atlas connection string.
"""

import asyncio
import sys
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import config


# A lead is "unassigned" if it has no assigned_to, or it's null/empty.
UNASSIGNED_QUERY = {
    "$or": [
        {"assigned_to": {"$exists": False}},
        {"assigned_to": None},
        {"assigned_to": ""},
    ]
}


async def migrate(dry_run: bool = False):
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB_NAME]

    print("=" * 60)
    print(f"UNASSIGNED-LEAD BACKFILL  (db: {config.MONGODB_DB_NAME})")
    print("=" * 60)

    await client.admin.command("ping")

    admin = await db.users.find_one(
        {"role": "admin", "is_active": True}, sort=[("created_at", 1), ("_id", 1)]
    )
    if not admin:
        print("[ABORT] No active admin found. Cannot backfill.")
        return

    admin_email = admin["email"]
    admin_name = admin.get("name", admin_email)

    total = await db.leads.count_documents({})
    affected = await db.leads.count_documents(UNASSIGNED_QUERY)
    print(f"Total leads: {total}")
    print(f"Unassigned leads to assign -> {admin_email}: {affected}")

    if dry_run:
        leads = await db.leads.find(
            UNASSIGNED_QUERY, {"lead_id": 1, "full_name": 1}
        ).to_list(None)
        for ld in leads:
            print(f"  WOULD ASSIGN: {ld.get('lead_id')}  ({ld.get('full_name', '')}) -> {admin_email}")
        print("[DRY RUN] No changes written.")
        return

    if not affected:
        print("[OK] Nothing to backfill.")
        return

    now = datetime.utcnow()
    result = await db.leads.update_many(
        UNASSIGNED_QUERY,
        {
            "$set": {
                "assigned_to": admin_email,
                "assigned_to_name": admin_name,
                "assigned_at": now,
            },
            "$push": {
                "audit_log": {
                    "timestamp": now,
                    "action": "backfill_assigned_to_admin",
                    "user": "system",
                    "old_value": None,
                    "new_value": admin_email,
                }
            },
        },
    )
    print(f"[OK] Assigned {result.modified_count} unassigned leads to {admin_email}.")

    remaining = await db.leads.count_documents(UNASSIGNED_QUERY)
    print(f"Unassigned leads remaining: {remaining}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
