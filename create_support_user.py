"""
Create support team user (Facilitator role)
Run this to create a test support user
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import config
from auth import hash_password
from datetime import datetime

async def create_support_user():
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB_NAME]

    try:
        # Check if user exists
        existing = await db.users.find_one({'email': 'support@example.com'})
        if existing:
            # Update existing user to ensure it's active and has correct password
            await db.users.update_one(
                {'email': 'support@example.com'},
                {'$set': {
                    'password_hash': hash_password('Demo@12345'),
                    'is_active': True,
                    'role': 'facilitator',
                    'name': 'Support Team User'
                }}
            )
            print('=' * 60)
            print('SUPPORT USER UPDATED AND ACTIVATED!')
            print('=' * 60)
            print(f'Email:    support@example.com')
            print(f'Password: Demo@12345')
            print(f'Role:     facilitator (Support Team)')
            print(f'Status:   ACTIVE')
            print()
            print('Login URL: http://localhost:8000/admin')
            print('=' * 60)
            return

        user = {
            'email': 'support@example.com',
            'password_hash': hash_password('Demo@12345'),
            'name': 'Support Team User',
            'role': 'facilitator',  # ← Support team role
            'is_active': True,
            'created_at': datetime.utcnow(),
            'login_count': 0
        }

        result = await db.users.insert_one(user)
        print('=' * 60)
        print('SUPPORT USER CREATED SUCCESSFULLY!')
        print('=' * 60)
        print(f'Email:    support@example.com')
        print(f'Password: Demo@12345')
        print(f'Role:     facilitator (Support Team)')
        print(f'User ID:  {result.inserted_id}')
        print()
        print('Login URL: http://localhost:8000/admin')
        print('=' * 60)

    except Exception as e:
        print(f'[ERROR] Failed to create user: {e}')
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(create_support_user())
