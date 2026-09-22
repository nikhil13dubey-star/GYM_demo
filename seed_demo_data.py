"""
Seed the demo database: sample gyms (from gyms.csv) + demo users.

Usage:
    python seed_demo_data.py

Reads MONGODB_URL / MONGODB_DB_NAME from the environment (see .env.example).
Safe to re-run: it clears and rebuilds the demo collections.
"""
import csv
from datetime import datetime

from pymongo import MongoClient

import config
from auth import hash_password

DEMO_PASSWORD = config.DEFAULT_ADMIN_PASSWORD
DEMO_USERS = [
    (config.DEFAULT_ADMIN_EMAIL, "Admin User", "admin"),
    ("nikhil@example.com", "Nikhil", "agent"),
    ("arjun@example.com", "Arjun", "agent"),
    ("kavya@example.com", "Kavya", "agent"),
]


def seed():
    db = MongoClient(config.MONGODB_URL)[config.MONGODB_DB_NAME]
    print(f"Seeding database '{config.MONGODB_DB_NAME}' at {config.MONGODB_URL}")

    for name in ("gyms", "users", "leads", "counters", "communications", "settings"):
        db[name].delete_many({})

    gyms = []
    with open("gyms.csv", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=1):
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            gyms.append({
                "gym_id": i,
                "gym_name": row["GymName"],
                "partner_name": row["PartnerName"],
                "address": row["Address"],
                "pincode": row["Pincode"],
                "city": row["City"],
                "state": row["State"],
                "latitude": lat,
                "longitude": lon,
                # GeoJSON is [lon, lat] and powers the $near "gyms near me" search
                "location": {"type": "Point", "coordinates": [lon, lat]},
                "amenities": [a.strip() for a in row["Amenities"].split(",") if a.strip()],
                "subscription_amount": int(row["SubscriptionAmount"]),
                "center_code": f"DG{i:04d}",
                "center_type": "GYM",
                "is_active": True,
                "created_at": datetime.utcnow(),
            })
    db.gyms.insert_many(gyms)

    db.users.insert_many([{
        "email": email,
        "name": name,
        "password_hash": hash_password(DEMO_PASSWORD),
        "role": role,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "login_count": 0,
    } for email, name, role in DEMO_USERS])

    print(f"  gyms:  {db.gyms.count_documents({})}")
    print(f"  users: {db.users.count_documents({})}  (password for all: {DEMO_PASSWORD})")
    print("Done. Start the app with: uvicorn main:app --reload")


if __name__ == "__main__":
    seed()
