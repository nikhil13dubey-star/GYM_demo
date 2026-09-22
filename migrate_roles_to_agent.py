"""
RBAC migration: collapse 3 roles -> 2 roles.

Relabels every user whose role is 'facilitator' or 'viewer' to 'agent'.
Admins are left untouched. Idempotent — safe to run multiple times.

Usage:
    python migrate_roles_to_agent.py            # migrate roles
    python migrate_roles_to_agent.py --dry-run  # show what would change, no writes

Run against the SAME MONGODB_URL / MONGODB_DB_NAME the app uses (set via .env
or environment). For prod, point it at the Atlas connection string.
"""

import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
import config


async def migrate(dry_run: bool = False):
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB_NAME]

    print("=" * 60)
    print(f"ROLE MIGRATION  (db: {config.MONGODB_DB_NAME})")
    print("=" * 60)

    await client.admin.command("ping")

    legacy = {"role": {"$in": ["facilitator", "viewer"]}}
    affected = await db.users.count_documents(legacy)

    # Report current distribution
    pipeline = [{"$group": {"_id": "$role", "count": {"$sum": 1}}}]
    dist = await db.users.aggregate(pipeline).to_list(None)
    print("Current roles:", {d["_id"]: d["count"] for d in dist})
    print(f"Users to relabel -> 'agent': {affected}")

    if dry_run:
        users = await db.users.find(legacy, {"email": 1, "role": 1}).to_list(None)
        for u in users:
            print(f"  WOULD CHANGE: {u['email']}  {u['role']} -> agent")
        print("[DRY RUN] No changes written.")
        return

    if affected:
        result = await db.users.update_many(legacy, {"$set": {"role": "agent"}})
        print(f"[OK] Updated {result.modified_count} users to role 'agent'.")
    else:
        print("[OK] Nothing to migrate.")

    dist2 = await db.users.aggregate(pipeline).to_list(None)
    print("Roles after migration:", {d["_id"]: d["count"] for d in dist2})
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
