"""
Migrate gyms.csv to MongoDB
Run this once to import all gym data
"""

import asyncio
import csv
from motor.motor_asyncio import AsyncIOMotorClient
import config

async def migrate_gyms():
    """Migrate gyms from CSV to MongoDB"""

    print("=" * 60)
    print("GYM MIGRATION: CSV to MongoDB")
    print("=" * 60)

    # Connect to MongoDB
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB_NAME]

    try:
        # Test connection
        await client.admin.command('ping')
        print("[OK] Connected to MongoDB")

        # Read CSV file
        gyms_data = []
        with open('gyms.csv', 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for idx, row in enumerate(reader, start=1):
                gym = {
                    'gym_id': idx,
                    'partner_name': row['PartnerName'].strip(),
                    'gym_name': row['GymName'].strip(),
                    'address': row['Address'].strip(),
                    'pincode': row['Pincode'].strip(),
                    'city': row['City'].strip(),
                    'state': row['State'].strip(),
                    'location': {
                        'type': 'Point',
                        'coordinates': [
                            float(row['Longitude']),  # longitude first for GeoJSON
                            float(row['Latitude'])
                        ]
                    },
                    'latitude': float(row['Latitude']),  # Keep for compatibility
                    'longitude': float(row['Longitude']),
                    'subscription_amount': int(row['SubscriptionAmount']),
                    'amenities': [a.strip() for a in row['Amenities'].split(',')],
                    'is_active': True
                }
                gyms_data.append(gym)

        print(f"[OK] Read {len(gyms_data)} gyms from CSV")

        # Drop existing collection (clean start)
        await db.gyms.drop()
        print("[OK] Dropped existing gyms collection")

        # Insert all gyms
        if gyms_data:
            result = await db.gyms.insert_many(gyms_data)
            print(f"[OK] Inserted {len(result.inserted_ids)} gyms into MongoDB")

        # Create indexes
        print("[OK] Creating indexes...")
        await db.gyms.create_index("gym_id", unique=True)
        await db.gyms.create_index("pincode")
        await db.gyms.create_index("city")
        await db.gyms.create_index("partner_name")
        await db.gyms.create_index([("location", "2dsphere")])
        await db.gyms.create_index("is_active")
        print("[OK] Indexes created")

        # Verify count
        count = await db.gyms.count_documents({})
        print(f"[OK] Total gyms in MongoDB: {count}")

        # Sample query test
        sample = await db.gyms.find_one({"pincode": "400053"})
        if sample:
            print(f"[OK] Sample gym: {sample['gym_name']} ({sample['city']})")

        print("=" * 60)
        print("[SUCCESS] MIGRATION COMPLETE!")
        print("=" * 60)

    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        raise

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(migrate_gyms())
