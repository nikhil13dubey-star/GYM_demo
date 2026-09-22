"""
Create initial admin user in MongoDB
Run this once after setting up database
"""

import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import config
from auth import hash_password

async def create_admin():
    """Create initial admin user"""

    print("=" * 60)
    print("CREATE ADMIN USER")
    print("=" * 60)

    # Connect to MongoDB
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB_NAME]

    try:
        # Test connection
        await client.admin.command('ping')
        print("[OK] Connected to MongoDB")

        # Check if admin already exists
        existing_admin = await db.users.find_one({"email": config.DEFAULT_ADMIN_EMAIL})
        if existing_admin:
            print(f"[WARNING] Admin user already exists: {config.DEFAULT_ADMIN_EMAIL}")
            print("   Skipping creation.")
            return

        # Create admin user
        admin_user = {
            "email": config.DEFAULT_ADMIN_EMAIL,
            "password_hash": hash_password(config.DEFAULT_ADMIN_PASSWORD),
            "name": config.DEFAULT_ADMIN_NAME,
            "role": "admin",
            "is_active": True,
            "is_email_verified": True,
            "created_at": datetime.utcnow(),
            "last_login": None,
            "last_login_ip": None,
            "login_count": 0,
            "password_changed_at": datetime.utcnow(),
            "password_reset_token": None,
            "password_reset_expires": None,
            "preferences": {
                "email_notifications": True,
                "leads_per_page": 20,
                "default_filters": {}
            }
        }

        result = await db.users.insert_one(admin_user)
        print(f"[OK] Admin user created successfully!")
        print(f"   Email: {config.DEFAULT_ADMIN_EMAIL}")
        print(f"   Password: {config.DEFAULT_ADMIN_PASSWORD}")
        print(f"   User ID: {result.inserted_id}")
        print()
        print("[IMPORTANT] Change the password after first login!")
        print("=" * 60)

    except Exception as e:
        print(f"[ERROR] Failed to create admin user: {e}")
        raise

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(create_admin())
