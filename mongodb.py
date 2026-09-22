"""
Gym Habit - MongoDB Database Connection
Async MongoDB client using Motor
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
import config

class MongoDB:
    """MongoDB connection manager"""

    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None
    _indexes_ready: bool = False

    @classmethod
    async def connect_db(cls):
        """Connect to MongoDB"""
        # Idempotent: startup calls this three times (app + two managers) and on a
        # serverless platform every cold start paid for three handshakes.
        if cls.client is not None and cls.db is not None:
            return

        try:
            cls.client = AsyncIOMotorClient(config.MONGODB_URL)
            cls.db = cls.client[config.MONGODB_DB_NAME]

            # Test connection
            await cls.client.admin.command('ping')
            print(f"[MongoDB] [OK] Connected to MongoDB: {config.MONGODB_DB_NAME}")

            # Create indexes
            await cls.create_indexes()

        except Exception as e:
            print(f"[MongoDB] [ERROR] Failed to connect: {e}")
            raise

    @classmethod
    async def close_db(cls):
        """Close MongoDB connection"""
        if cls.client:
            cls.client.close()
            cls.client = None
            cls.db = None
            cls._indexes_ready = False
            print("[MongoDB] [OK] Disconnected from MongoDB")

    @classmethod
    async def create_indexes(cls):
        """
        Create any missing indexes (once per process).

        Existing index names are read first so an already-provisioned database
        costs a handful of round trips at boot instead of one per index.
        """
        if cls._indexes_ready:
            return
        try:
            existing = {}
            for coll in ("gyms", "leads", "users", "communications"):
                try:
                    existing[coll] = set(await cls.db[coll].index_information())
                except Exception:
                    existing[coll] = set()
            expected = {
                "gyms": {"gym_id_1", "pincode_1", "city_1", "partner_name_1",
                         "location_2dsphere", "is_active_1", "center_code_1"},
                "leads": {"lead_id_1", "email_1", "phone_1", "created_at_-1", "status_1",
                          "payment.status_1", "status_1_payment.status_1_created_at_-1",
                          "payment_link_unique_ci"},
                "users": {"email_1", "role_1", "is_active_1"},
                "communications": {"sent_at_-1", "lead_id_1_sent_at_-1", "email_type_1", "status_1"},
            }
            if all(expected[c] <= existing.get(c, set()) for c in expected):
                cls._indexes_ready = True
                print("[MongoDB] [OK] Indexes already present")
                return
        except Exception:
            pass  # fall through and create them the normal way

        try:
            # Gyms collection indexes
            await cls.db.gyms.create_index("gym_id", unique=True)
            await cls.db.gyms.create_index("pincode")
            await cls.db.gyms.create_index("city")
            await cls.db.gyms.create_index("partner_name")
            await cls.db.gyms.create_index([("location", "2dsphere")])
            await cls.db.gyms.create_index("is_active")
            await cls.db.gyms.create_index("center_code")  # for CSV upsert lookups

            # Leads collection indexes
            await cls.db.leads.create_index("lead_id", unique=True)
            await cls.db.leads.create_index("email")
            await cls.db.leads.create_index("phone")
            await cls.db.leads.create_index([("created_at", -1)])
            await cls.db.leads.create_index("status")
            await cls.db.leads.create_index("payment.status")
            await cls.db.leads.create_index([("status", 1), ("payment.status", 1), ("created_at", -1)])

            # Reference ID (payment.payment_link) — UNIQUE, CASE-INSENSITIVE,
            # and ONLY indexed when the field is a string (excludes null/missing).
            # This is the database-level guard against the race condition where two
            # concurrent updates could both pass the application-level dup-check.
            # NOTE: cannot combine collation with partialFilterExpression on $type in
            # all MongoDB versions, so we use $exists+$ne instead.
            try:
                await cls.db.leads.create_index(
                    "payment.payment_link",
                    unique=True,
                    partialFilterExpression={"payment.payment_link": {"$type": "string"}},
                    collation={"locale": "en", "strength": 2},
                    name="payment_link_unique_ci"
                )
            except Exception as idx_err:
                # If existing data has duplicates, the index will fail to build.
                # Log but don't crash startup — the app-level check still applies.
                print(f"[MongoDB] [WARNING] Could not create unique index on payment.payment_link: {idx_err}")

            # Users collection indexes
            await cls.db.users.create_index("email", unique=True)
            await cls.db.users.create_index("role")
            await cls.db.users.create_index("is_active")

            # Communications log indexes (grouped-by-lead listing + timeline)
            await cls.db.communications.create_index([("sent_at", -1)])
            await cls.db.communications.create_index([("lead_id", 1), ("sent_at", -1)])
            await cls.db.communications.create_index("email_type")
            await cls.db.communications.create_index("status")

            cls._indexes_ready = True
            print("[MongoDB] [OK] Indexes created successfully")

        except Exception as e:
            print(f"[MongoDB] [WARNING] Index creation warning: {e}")

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        """Get database instance"""
        if cls.db is None:
            raise Exception("Database not connected. Call connect_db() first.")
        return cls.db


# Convenience function to get database
def get_database() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance"""
    return MongoDB.get_db()
