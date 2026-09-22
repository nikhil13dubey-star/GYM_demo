"""
Gym Habit - MongoDB Database Layer
Handles MongoDB operations for gyms and leads
"""

import math
from datetime import datetime
from typing import List, Dict, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import config
from mongodb import MongoDB


# Fields excluded from LIST queries (cards don't need them) — keeps the
# ~1700-gym payload small and reduces data fetched from Atlas.
LIST_PROJECTION = {"plans": 0, "custom_plans": 0, "subscription_plans_list": 0, "location": 0}

# Payment statuses that mean "the customer has paid". A legacy build wrote
# 'completed' (see _format_lead), which the display layer already surfaces as
# 'paid'. Every paid-gate MUST treat them the same, or leads show as Paid in the
# UI but get rejected by write guards (e.g. Activate/Invoice/emails).
PAID_STATUSES = ("paid", "completed")


def is_paid(payment: Optional[Dict]) -> bool:
    """True if the lead's payment counts as paid ('paid' or legacy 'completed')."""
    return isinstance(payment, dict) and payment.get("status") in PAID_STATUSES


class MongoGymDatabase:
    """Manages gym data from MongoDB"""

    def __init__(self):
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def initialize(self):
        """Initialize MongoDB connection"""
        await MongoDB.connect_db()
        self.db = MongoDB.db

    async def get_all_partners(self) -> List[Dict[str, any]]:
        """
        Get unique list of partners from partners collection merged with gym-derived partners
        Returns: [{"name": "Cult", "count": 10, "description": "...", "icon": "..."}, ...]
        """
        # Get partners from partners collection
        partners_cursor = self.db.partners.find({})
        partners_docs = await partners_cursor.to_list(None)

        # Create a dict with partner info from partners collection
        partners_dict = {}
        for p in partners_docs:
            partners_dict[p['name']] = {
                'name': p['name'],
                'description': p.get('description', ''),
                'icon': p.get('icon'),
                'count': 0  # Will be updated from gyms
            }

        # Get gym counts by partner
        pipeline = [
            {"$match": {"is_active": True}},
            {
                "$group": {
                    "_id": "$partner_name",
                    "count": {"$sum": 1}
                }
            }
        ]

        gym_counts = await self.db.gyms.aggregate(pipeline).to_list(None)

        # Merge gym counts with partner info
        for gc in gym_counts:
            partner_name = gc['_id']
            if partner_name in partners_dict:
                partners_dict[partner_name]['count'] = gc['count']
            else:
                # Partner exists in gyms but not in partners collection
                partners_dict[partner_name] = {
                    'name': partner_name,
                    'description': '',
                    'icon': None,
                    'count': gc['count']
                }

        # Convert to list and sort
        partners_list = list(partners_dict.values())
        partners_list.sort(key=lambda x: x['name'])

        return partners_list

    async def get_gyms_by_partner(self, partner: str) -> List[Dict]:
        """
        Filter gyms by partner name
        Args:
            partner: Partner name (e.g., "Cult")
        Returns: List of gym dictionaries
        """
        if not partner:
            cursor = self.db.gyms.find({"is_active": True}, LIST_PROJECTION)
            gyms = await cursor.to_list(None)
            return [self._format_gym(g, summary=True) for g in gyms]

        cursor = self.db.gyms.find({
            "partner_name": {"$regex": f"^{partner}$", "$options": "i"},
            "is_active": True
        }, LIST_PROJECTION)
        gyms = await cursor.to_list(None)
        return [self._format_gym(g, summary=True) for g in gyms]

    async def get_all_gyms(self) -> List[Dict]:
        """Get all active gyms (summary fields only — no heavy plan arrays)"""
        cursor = self.db.gyms.find({"is_active": True}, LIST_PROJECTION)
        gyms = await cursor.to_list(None)
        return [self._format_gym(g, summary=True) for g in gyms]

    async def get_gym_by_id(self, gym_id: int) -> Optional[Dict]:
        """
        Get single gym by ID
        Args:
            gym_id: Gym ID
        Returns: Gym dictionary or None
        """
        gym = await self.db.gyms.find_one({"gym_id": gym_id, "is_active": True})
        if gym:
            return self._format_gym(gym)
        return None

    async def search_by_pincode(self, pincode: str, limit: int = 10) -> List[Dict]:
        """
        Search gyms by pincode (instant, no distance calculation)
        Args:
            pincode: 6-digit pincode
            limit: Max results
        Returns: List of gyms in that pincode
        """
        # Exact pincode match
        cursor = self.db.gyms.find({
            "pincode": pincode,
            "is_active": True
        }, LIST_PROJECTION).limit(limit)

        exact_matches = await cursor.to_list(limit)

        if exact_matches:
            return [self._format_gym(g, summary=True) for g in exact_matches]

        # Try nearby pincodes (same first 3 digits)
        prefix = pincode[:3]
        cursor = self.db.gyms.find({
            "pincode": {"$regex": f"^{prefix}"},
            "is_active": True
        }, LIST_PROJECTION).limit(limit)

        nearby_gyms = await cursor.to_list(limit)
        return [self._format_gym(g, summary=True) for g in nearby_gyms]

    async def search_by_city(self, city: str, limit: int = 100) -> List[Dict]:
        """
        Get gyms in a specific city
        Args:
            city: City name
            limit: Max results
        Returns: List of gyms in that city
        """
        cursor = self.db.gyms.find({
            "city": {"$regex": f"^{city}$", "$options": "i"},
            "is_active": True
        }, LIST_PROJECTION).limit(limit)

        gyms = await cursor.to_list(limit)
        return [self._format_gym(g, summary=True) for g in gyms]

    async def get_nearby_gyms(
        self,
        user_lat: float,
        user_lon: float,
        partner: Optional[str] = None,
        city: Optional[str] = None,
        limit: int = 10,
        max_distance_km: int = 100
    ) -> List[Dict]:
        """
        Find nearest gyms using MongoDB geospatial query
        Args:
            user_lat: User's latitude
            user_lon: User's longitude
            partner: Optional partner filter
            city: Optional city filter (speeds up search)
            limit: Max number of results (default: 10)
            max_distance_km: Maximum distance in kilometers (default: 100)
        Returns: List of gyms sorted by distance
        """
        # Build query
        query = {
            "is_active": True,
            "location": {
                "$near": {
                    "$geometry": {
                        "type": "Point",
                        "coordinates": [user_lon, user_lat]  # GeoJSON uses [lon, lat]
                    },
                    "$maxDistance": max_distance_km * 1000  # Convert to meters
                }
            }
        }

        # Add partner filter if provided
        if partner:
            query["partner_name"] = {"$regex": f"^{partner}$", "$options": "i"}

        # Add city filter if provided
        if city:
            query["city"] = {"$regex": f"^{city}$", "$options": "i"}

        # Execute query (projection excludes only RETURNED fields; the $near
        # still uses the 2dsphere index, so dropping `location` from output is safe)
        cursor = self.db.gyms.find(query, LIST_PROJECTION).limit(limit)
        gyms = await cursor.to_list(limit)

        # Calculate distances and format
        results = []
        for gym in gyms:
            formatted = self._format_gym(gym, summary=True)
            # Calculate haversine distance for accurate km
            formatted['distance'] = haversine_distance(
                user_lat, user_lon,
                formatted['latitude'], formatted['longitude']
            )
            results.append(formatted)

        return results

    async def create_gym(
        self,
        gym_name: str,
        partner_name: str,
        address: str,
        city: str,
        state: str,
        pincode: str,
        latitude: float,
        longitude: float,
        amenities: List[str],
        subscription_amount: int = 1499,
        icon: str = None,
        custom_plans: dict = None,
        center_code: str = None,
        center_type: str = None,
        plans: List[dict] = None
    ) -> int:
        """
        Create a new gym entry
        Args:
            gym_name: Name of the gym
            partner_name: Partner/Provider name (e.g., "Cult")
            address: Full address
            city: City name
            state: State name
            pincode: 6-digit pincode
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            amenities: List of amenities
            subscription_amount: Starting subscription amount (default: 1499)
            center_code: Center code (e.g., CG0017)
            center_type: Center type (GX, Cult Center, GYM, SPORTS)
            plans: List of plan objects [{plan_name, mrp, discount, price}]
        Returns: New gym_id
        """
        # Generate new gym_id
        max_gym = await self.db.gyms.find_one(sort=[("gym_id", -1)])
        new_gym_id = (max_gym['gym_id'] + 1) if max_gym else 1

        # Create gym document
        new_gym = {
            'gym_id': new_gym_id,
            'gym_name': gym_name,
            'partner_name': partner_name,
            'address': address,
            'city': city,
            'state': state,
            'pincode': pincode,
            'latitude': latitude,
            'longitude': longitude,
            'location': {
                'type': 'Point',
                'coordinates': [longitude, latitude]  # GeoJSON format [lon, lat]
            },
            'amenities': amenities,
            'subscription_amount': subscription_amount,
            'is_active': True,
            'icon': icon,
            'created_at': datetime.utcnow()
        }

        # Add new fields
        if center_code:
            new_gym['center_code'] = center_code
        if center_type:
            new_gym['center_type'] = center_type
        if plans:
            new_gym['plans'] = plans

        # Add custom plans if provided (legacy support)
        if custom_plans:
            new_gym['custom_plans'] = custom_plans

        # Insert into MongoDB
        await self.db.gyms.insert_one(new_gym)
        print(f"[CREATED] Gym created: {gym_name} (ID: {new_gym_id}, Center: {center_code}, Plans: {len(plans) if plans else 0})")

        return new_gym_id

    async def upsert_gym_by_center_code(
        self,
        gym_name: str,
        partner_name: str,
        address: str,
        city: str,
        state: str,
        pincode: str,
        latitude: float,
        longitude: float,
        amenities: List[str],
        subscription_amount: int,
        center_code: str,
        center_type: str = None,
        plans: List[dict] = None
    ) -> dict:
        """
        Upsert a gym keyed on center_code (used by CSV bulk upload).
          - If a gym with this center_code already exists, UPDATE it in place
            (refresh plans/prices and all other fields) while KEEPING its gym_id
            so existing leads stay linked. Prefers an active match.
          - Otherwise, INSERT a new gym.

        Returns: {"gym_id": int, "action": "updated"|"created"}
        """
        existing = (
            await self.db.gyms.find_one({"center_code": center_code, "is_active": True})
            or await self.db.gyms.find_one({"center_code": center_code})
        )

        if existing:
            update_data = {
                'gym_name': gym_name,
                'partner_name': partner_name,
                'address': address,
                'city': city,
                'state': state,
                'pincode': pincode,
                'latitude': latitude,
                'longitude': longitude,
                'location': {'type': 'Point', 'coordinates': [longitude, latitude]},
                'amenities': amenities,
                'subscription_amount': subscription_amount,
                'center_type': center_type,
                'plans': plans or [],
                'is_active': True,  # ensure an updated gym is visible
                'updated_at': datetime.utcnow(),
            }
            await self.db.gyms.update_one({'_id': existing['_id']}, {'$set': update_data})
            print(f"[UPDATED] Gym updated: {gym_name} (ID: {existing['gym_id']}, Center: {center_code}, Plans: {len(plans) if plans else 0})")
            return {"gym_id": existing['gym_id'], "action": "updated"}

        gym_id = await self.create_gym(
            gym_name=gym_name, partner_name=partner_name, address=address, city=city,
            state=state, pincode=pincode, latitude=latitude, longitude=longitude,
            amenities=amenities, subscription_amount=subscription_amount,
            center_code=center_code, center_type=center_type, plans=plans
        )
        return {"gym_id": gym_id, "action": "created"}


    async def update_gym(
        self,
        gym_id: int,
        gym_name: str,
        partner_name: str,
        address: str,
        city: str,
        state: str,
        pincode: str,
        latitude: float,
        longitude: float,
        amenities: List[str],
        subscription_amount: int = 1499,
        icon: str = None,
        custom_plans: dict = None
    ) -> bool:
        """
        Update an existing gym
        Returns: True if updated, False if gym not found
        """
        update_data = {
            'gym_name': gym_name,
            'partner_name': partner_name,
            'address': address,
            'city': city,
            'state': state,
            'pincode': pincode,
            'latitude': latitude,
            'longitude': longitude,
            'location': {
                'type': 'Point',
                'coordinates': [longitude, latitude]
            },
            'amenities': amenities,
            'subscription_amount': subscription_amount,
            'icon': icon,
            'updated_at': datetime.utcnow()
        }

        # Add custom plans if provided, otherwise remove them
        if custom_plans:
            update_data['custom_plans'] = custom_plans
        else:
            update_data['custom_plans'] = None

        result = await self.db.gyms.update_one(
            {'gym_id': gym_id, 'is_active': True},
            {'$set': update_data}
        )

        return result.matched_count > 0

    async def update_partner(
        self,
        old_name: str,
        new_name: str,
        description: str = "",
        icon: str = None
    ) -> bool:
        """
        Update an existing partner (or create if doesn't exist in partners collection)
        If name changes, also update all associated gyms
        Returns: True if updated
        """
        update_data = {
            'name': new_name,
            'description': description,
            'icon': icon,
            'updated_at': datetime.utcnow()
        }

        # Use upsert to create if doesn't exist
        # This handles partners that exist in gyms but not in partners collection
        result = await self.db.partners.update_one(
            {'name': old_name},
            {
                '$set': update_data,
                '$setOnInsert': {'created_at': datetime.utcnow()}
            },
            upsert=True  # Insert if doesn't exist
        )

        # If partner name changed, update all gyms with this partner
        if old_name != new_name:
            await self.db.gyms.update_many(
                {'partner_name': old_name},
                {'$set': {'partner_name': new_name}}
            )

        print(f"[UPDATED] Partner '{old_name}' -> '{new_name}' (upserted={result.upserted_id is not None})")
        return True  # Always return True since upsert guarantees success

    async def delete_gym(self, gym_id: int) -> bool:
        """
        Soft delete a gym (mark as inactive)
        Args:
            gym_id: Gym ID to delete
        Returns: True if deleted, False if not found
        """
        result = await self.db.gyms.update_one(
            {"gym_id": gym_id},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": datetime.utcnow()
                }
            }
        )

        if result.modified_count > 0:
            print(f"[DELETED] Gym deleted: ID {gym_id}")
            return True
        return False

    async def delete_partner(self, partner_name: str) -> int:
        """
        Delete partner from partners collection and soft delete all gyms
        Args:
            partner_name: Partner name to delete
        Returns: Number of gyms deleted
        """
        # Soft delete all gyms of this partner
        gym_result = await self.db.gyms.update_many(
            {"partner_name": {"$regex": f"^{partner_name}$", "$options": "i"}},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": datetime.utcnow()
                }
            }
        )

        # Delete partner from partners collection
        await self.db.partners.delete_one({"name": partner_name})

        print(f"[DELETED] Partner deleted: {partner_name} ({gym_result.modified_count} gyms)")
        return gym_result.modified_count

    async def create_partner_entry(self, partner_name: str, description: str = "", icon: str = None) -> bool:
        """
        Create a partner entry in partners collection
        Args:
            partner_name: Partner name
            description: Partner description
            icon: Partner icon (emoji or base64 image)
        Returns: True if created, False if already exists
        """
        # Check if partner already exists in partners collection
        existing = await self.db.partners.find_one({"name": partner_name})

        if existing:
            return False  # Partner already exists

        # Create partner document
        partner_doc = {
            'name': partner_name,
            'description': description,
            'icon': icon,
            'created_at': datetime.utcnow()
        }

        await self.db.partners.insert_one(partner_doc)
        print(f"[INFO] Partner '{partner_name}' created in partners collection")
        return True

    def _format_gym(self, gym: Dict, summary: bool = False) -> Dict:
        """
        Convert MongoDB gym document to API format.
        Args:
            gym: MongoDB document
            summary: when True, omit the heavy plan arrays (plans / custom_plans /
                     subscription_plans_list). Used by LIST endpoints so a payload
                     of ~1700 gyms stays small; the per-gym detail endpoint passes
                     summary=False to return the full plan data.
        Returns: Formatted gym dictionary
        """
        # Normalize amenities to a list of strings.
        # Some amenities contain commas inside the value (e.g. "Dance Fitness, Yoga, HRX"),
        # so we MUST preserve the list structure end-to-end. Comma-joining corrupts those.
        raw_amenities = gym.get('amenities', [])
        if isinstance(raw_amenities, list):
            amenities_list = [str(a).strip() for a in raw_amenities if str(a).strip()]
        elif isinstance(raw_amenities, str):
            # Legacy/unimported data stored as string — split by bullet first, then comma
            if '•' in raw_amenities:
                amenities_list = [a.strip() for a in raw_amenities.split('•') if a.strip()]
            else:
                amenities_list = [a.strip() for a in raw_amenities.split(',') if a.strip()]
        else:
            amenities_list = []

        formatted = {
            'id': gym['gym_id'],
            'partner_name': gym['partner_name'],
            'gym_name': gym['gym_name'],
            'address': gym['address'],
            'pincode': gym['pincode'],
            'city': gym['city'],
            'state': gym['state'],
            'latitude': gym['latitude'],
            'longitude': gym['longitude'],
            'subscription_amount': gym['subscription_amount'],
            'amenities': amenities_list
        }

        # Add optional lightweight fields needed by cards
        if 'icon' in gym and gym['icon']:
            formatted['icon'] = gym['icon']
        if 'center_code' in gym and gym['center_code']:
            formatted['center_code'] = gym['center_code']
        if 'center_type' in gym and gym['center_type']:
            formatted['center_type'] = gym['center_type']

        # Heavy plan arrays — only for detail responses, never for list payloads.
        if not summary:
            if 'custom_plans' in gym and gym['custom_plans']:
                formatted['custom_plans'] = gym['custom_plans']
            if 'plans' in gym and gym['plans']:
                formatted['plans'] = gym['plans']
            # Frontend checks `subscription_plans_list` to render the rich named-plan UI
            if 'subscription_plans_list' in gym and gym['subscription_plans_list']:
                formatted['subscription_plans_list'] = gym['subscription_plans_list']

        return formatted


class MongoLeadManager:
    """Manages subscription/lead requests in MongoDB"""

    def __init__(self):
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def initialize(self):
        """Initialize MongoDB connection"""
        await MongoDB.connect_db()
        self.db = MongoDB.db

    async def save_lead(self, lead_data: Dict, assignee: Optional[Dict] = None) -> str:
        """
        Save subscription request/lead
        Args:
            lead_data: Dictionary with user info and gym details
            assignee: Optional {'email','name','via'} for round-robin auto-assignment.
                      When provided, the lead is created already owned (never momentarily
                      unassigned) and an 'auto_assigned' audit entry is recorded.
        Returns: Lead ID
        """
        # Generate lead ID
        date_str = datetime.now().strftime('%Y%m%d')

        # Count existing leads for today
        count = await self.db.leads.count_documents({
            "lead_id": {"$regex": f"^{config.LEAD_ID_PREFIX}_{date_str}"}
        })

        lead_id = f"{config.LEAD_ID_PREFIX}_{date_str}_{(count + 1):04d}"

        # Create lead document
        new_lead = {
            'lead_id': lead_id,
            'created_at': datetime.utcnow(),
            'gym_id': lead_data['gym_id'],
            'gym_name': lead_data['gym_name'],
            'partner_name': lead_data['partner_name'],
            'full_name': lead_data['full_name'],
            'email': lead_data.get('email', ''),
            'phone': lead_data['phone'],
            'preferred_plan': lead_data['preferred_plan'],
            'billing_address': lead_data.get('billing_address', ''),
            'message': lead_data.get('message', ''),
            'user_location': {
                'latitude': lead_data.get('user_latitude'),
                'longitude': lead_data.get('user_longitude'),
                'city': lead_data.get('user_city')
            },
            'status': 'new',  # new, contacted, interested, not_interested, closed
            'payment': {
                'status': 'pending',  # pending, link_shared, paid, failed
                'amount': None,
                'payment_link': None,
                'updated_at': None
            },
            'comments': [],
            'audit_log': []
        }

        # Round-robin auto-assignment at creation (lead is never momentarily unassigned)
        if assignee and assignee.get('email'):
            now = datetime.utcnow()
            new_lead['assigned_to'] = assignee['email']
            new_lead['assigned_to_name'] = assignee.get('name', assignee['email'])
            new_lead['assigned_at'] = now
            new_lead['audit_log'].append({
                'timestamp': now,
                'action': 'auto_assigned',
                'user': 'system',
                'old_value': None,
                'new_value': assignee['email'],
                'via': assignee.get('via', 'round_robin')
            })

        # Insert into MongoDB
        result = await self.db.leads.insert_one(new_lead)
        print(f"[SAVED] Lead saved: {lead_id} -> {new_lead.get('assigned_to', 'unassigned')}")

        return lead_id

    async def get_all_leads(
        self,
        skip: int = 0,
        limit: int = 20,
        status_filter: Optional[str] = None,
        payment_status_filter: Optional[str] = None,
        city_filter: Optional[str] = None,
        assigned_to_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict:
        """
        Get all leads with filters and pagination
        Args:
            skip: Number of records to skip (for pagination)
            limit: Max records to return
            status_filter: Filter by lead status
            payment_status_filter: Filter by payment status
            city_filter: Filter by city
            date_from: Filter by start date
            date_to: Filter by end date
        Returns: {"leads": [...], "total": 100, "page": 1, "pages": 5}
        """
        # Build query
        query = {}

        if status_filter:
            query['status'] = status_filter

        if payment_status_filter:
            query['payment.status'] = payment_status_filter

        if city_filter:
            query['user_location.city'] = {"$regex": f"^{city_filter}$", "$options": "i"}

        if assigned_to_filter:
            query['assigned_to'] = assigned_to_filter

        if date_from or date_to:
            query['created_at'] = {}
            if date_from:
                query['created_at']['$gte'] = date_from
            if date_to:
                query['created_at']['$lte'] = date_to

        # Get total count
        total = await self.db.leads.count_documents(query)

        # Get leads
        cursor = self.db.leads.find(query).sort("created_at", -1).skip(skip).limit(limit)
        leads = await cursor.to_list(limit)

        # Format leads
        formatted_leads = [self._format_lead(lead) for lead in leads]

        return {
            "leads": formatted_leads,
            "total": total,
            "page": (skip // limit) + 1,
            "pages": (total + limit - 1) // limit,  # Ceiling division
            "per_page": limit
        }

    async def assign_lead(self, lead_id: str, assigned_to_email: str, assigned_to_name: str) -> bool:
        """
        Assign a lead to a user (tracks who is working on the lead)
        """
        result = await self.db.leads.update_one(
            {'lead_id': lead_id},
            {
                '$set': {
                    'assigned_to': assigned_to_email,
                    'assigned_to_name': assigned_to_name,
                    'assigned_at': datetime.utcnow()
                }
            }
        )
        return result.matched_count > 0

    async def reassign_lead(self, lead_id: str, assignee_email: str, assignee_name: str, changed_by: str) -> bool:
        """
        Admin reassignment of a lead to another user, with audit logging.
        Unlike assign_lead (silent claim), this records a 'lead_reassigned' audit entry.
        """
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return False

        old_owner = lead.get('assigned_to')

        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "lead_reassigned",
            "user": changed_by,
            "old_value": old_owner,
            "new_value": assignee_email
        }

        result = await self.db.leads.update_one(
            {'lead_id': lead_id},
            {
                '$set': {
                    'assigned_to': assignee_email,
                    'assigned_to_name': assignee_name,
                    'assigned_at': datetime.utcnow()
                },
                '$push': {'audit_log': audit_entry}
            }
        )
        return result.matched_count > 0

    async def pick_next_assignee(self) -> Optional[Dict]:
        """
        Round-robin selection of the next owner for a new (or redistributed) lead.

        - Cycles through active agents (role=='agent', is_active==True), ordered by
          created_at then _id for a stable rotation, using an atomic counter in the
          `counters` collection so concurrent submissions distribute evenly.
        - If NO active agent exists, falls back to the oldest active admin.
        - Returns {'email','name','via'} ('via' is 'round_robin' or 'admin_fallback'),
          or None only if there are literally no active users (defensive).
        """
        agents = await self.db.users.find(
            {"role": "agent", "is_active": True}
        ).sort([("created_at", 1), ("_id", 1)]).to_list(None)

        if agents:
            result = await self.db.counters.find_one_and_update(
                {"_id": "lead_rotation"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=True
            )
            seq = result.get("seq", 1) if result else 1
            chosen = agents[(seq - 1) % len(agents)]
            return {
                "email": chosen["email"],
                "name": chosen.get("name", chosen["email"]),
                "via": "round_robin"
            }

        # Fallback: no active agent -> oldest active admin so the lead is never unowned
        admin = await self.db.users.find_one(
            {"role": "admin", "is_active": True}, sort=[("created_at", 1), ("_id", 1)]
        )
        if admin:
            return {
                "email": admin["email"],
                "name": admin.get("name", admin["email"]),
                "via": "admin_fallback"
            }

        return None

    async def reassign_open_leads_from_agent(self, agent_email: str, changed_by: str) -> Dict:
        """
        Redistribute a (just-deactivated) agent's OPEN leads across remaining active
        agents via round-robin (admin fallback if none left). A lead is "open" when its
        status is not 'closed' AND its payment is not 'paid' -- closed/paid leads stay
        attributed to the original agent for records. Each move is audit-logged.

        Returns {'reassigned': n, 'details': [{'lead_id','new_owner'}, ...]}.
        """
        open_leads = await self.db.leads.find({
            "assigned_to": agent_email,
            "status": {"$ne": "closed"},
            "payment.status": {"$nin": list(PAID_STATUSES)}
        }).to_list(None)

        details = []
        for lead in open_leads:
            assignee = await self.pick_next_assignee()
            if not assignee:
                break
            now = datetime.utcnow()
            await self.db.leads.update_one(
                {"lead_id": lead["lead_id"]},
                {
                    "$set": {
                        "assigned_to": assignee["email"],
                        "assigned_to_name": assignee["name"],
                        "assigned_at": now
                    },
                    "$push": {"audit_log": {
                        "timestamp": now,
                        "action": "reassigned_on_deactivate",
                        "user": changed_by,
                        "old_value": agent_email,
                        "new_value": assignee["email"]
                    }}
                }
            )
            details.append({"lead_id": lead["lead_id"], "new_owner": assignee["email"]})

        return {"reassigned": len(details), "details": details}

    async def get_lead_by_id(self, lead_id: str) -> Optional[Dict]:
        """
        Get a single lead by ID
        Args:
            lead_id: Lead ID (e.g., GYM_20251214_0001)
        Returns: Lead document or None
        """
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if lead:
            return self._format_lead(lead)
        return None

    async def update_lead_status(
        self,
        lead_id: str,
        new_status: str,
        updated_by: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Update lead status with audit logging.

        Rules:
          - 'activated' is the FINAL state: once a lead is Activated, its status
            cannot change again.
          - Once payment.status == 'paid', the ONLY permitted status change is to
            'activated'. All other status changes stay locked.
          - 'activated' may only be set after payment.status == 'paid'.

        Returns: True if updated, False if lead not found
        Raises: ValueError on validation failure (caller maps to HTTP 400)
        """
        # Get current lead
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return False

        old_status = lead.get('status', 'new')
        paid = is_paid(lead.get('payment'))

        # 'activated' is terminal — no further status changes once set
        if old_status == 'activated':
            raise ValueError(
                "This lead is already Activated (final state) and its status cannot be changed."
            )

        if paid:
            # After payment is paid, the only allowed transition is to 'activated'
            if new_status != 'activated':
                raise ValueError(
                    "Payment is marked 'paid'. The only allowed status change now is to 'Activated'."
                )
        else:
            # 'activated' requires a paid payment first
            if new_status == 'activated':
                raise ValueError(
                    "'Activated' can only be set after payment status is 'paid'."
                )

        # Create audit entry
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "status_change",
            "user": updated_by,
            "old_value": old_status,
            "new_value": new_status,
            "reason": reason
        }

        # Update lead
        result = await self.db.leads.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "status": new_status,
                    "updated_at": datetime.utcnow()
                },
                "$push": {"audit_log": audit_entry}
            }
        )

        return result.modified_count > 0

    async def add_comment(
        self,
        lead_id: str,
        comment_text: str,
        added_by: str
    ) -> bool:
        """
        Add a comment to a lead
        Args:
            lead_id: Lead ID
            comment_text: Comment content
            added_by: User email who added the comment
        Returns: True if added, False if lead not found
        """
        comment = {
            "timestamp": datetime.utcnow(),
            "user": added_by,
            "text": comment_text
        }

        # Create audit entry
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "comment_added",
            "user": added_by,
            "comment": comment_text
        }

        result = await self.db.leads.update_one(
            {"lead_id": lead_id},
            {
                "$set": {"updated_at": datetime.utcnow()},
                "$push": {
                    "comments": comment,
                    "audit_log": audit_entry
                }
            }
        )

        return result.modified_count > 0

    async def _generate_recon_id(self) -> str:
        """
        Atomically generate next sequential Recon ID (HHGYM-00001, HHGYM-00002, ...)
        Uses a dedicated counters collection with findOneAndUpdate $inc for race-safety.
        Returns: Formatted recon ID string
        """
        result = await self.db.counters.find_one_and_update(
            {"_id": "recon_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True
        )
        seq = result.get("seq", 1) if result else 1
        return f"HHGYM-{seq:05d}"

    async def peek_next_recon_id(self) -> str:
        """
        Predict the next Recon ID WITHOUT incrementing the counter.
        Used to show a preview to the admin in the UI before save.
        The actual ID generated on save may differ if another admin saves first.
        Returns: Formatted recon ID string (predicted)
        """
        counter = await self.db.counters.find_one({"_id": "recon_id"})
        current_seq = counter.get("seq", 0) if counter else 0
        return f"HHGYM-{(current_seq + 1):05d}"

    async def find_lead_by_reference_id(self, reference_id: str, exclude_lead_id: Optional[str] = None) -> Optional[str]:
        """
        Check if a Reference ID is already used by another lead.
        Compares case-insensitively and ignores leading/trailing whitespace
        so 'txn_001', ' TXN_001 ', and 'TxN_001' are all treated as duplicates.
        """
        if not reference_id:
            return None
        normalized = reference_id.strip()
        if not normalized:
            return None
        # Escape regex special chars in the reference id, then anchor + case-insensitive match
        import re as _re
        pattern = f"^{_re.escape(normalized)}$"
        query = {"payment.payment_link": {"$regex": pattern, "$options": "i"}}
        if exclude_lead_id:
            query["lead_id"] = {"$ne": exclude_lead_id}
        existing = await self.db.leads.find_one(query)
        return existing["lead_id"] if existing else None

    async def update_payment(
        self,
        lead_id: str,
        payment_status: str,
        updated_by: str,
        payment_link: Optional[str] = None,
        amount: Optional[int] = None
    ) -> bool:
        """
        Update payment information for a lead.

        Recon ID generation rules (strict):
          - ONLY when payment_status == 'paid' AND payment_link (Reference ID) is provided
          - Reference ID must be unique across all leads
          - Once a lead has a recon_id, it is never regenerated

        Reference ID rules:
          - Can only be SET or CHANGED when payment_status == 'paid'
          - Must be unique across all leads (no two leads can share a Reference ID)

        Args:
            lead_id: Lead ID
            payment_status: Payment status (pending, link_shared, paid, failed)
            updated_by: User email who made the change
            payment_link: Reference ID (Razorpay transaction ID) — stored in legacy field name
            amount: Payment amount
        Returns: True if updated, False if lead not found
        Raises: ValueError on validation failure (caller should map to HTTP 400)
        """
        # Get current lead
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return False

        # Block payment changes on CLOSED leads — the deal is dead, no transactions expected.
        if lead.get('status') == 'closed':
            raise ValueError(
                "Cannot update payment on a closed lead. "
                "Reopen the lead first by changing its status."
            )

        old_payment = lead.get('payment', {})
        old_payment_link = old_payment.get('payment_link')

        # Normalize incoming Reference ID — trim whitespace.
        # Case is preserved as entered, but duplicate-check is case-insensitive.
        if payment_link is not None:
            payment_link = payment_link.strip()

        # ----- VALIDATION -----
        is_setting_reference = payment_link is not None and payment_link != ""
        # Compare against old reference case-insensitively to detect "real" changes
        old_pl_norm = (old_payment_link or "").strip().lower() if old_payment_link else ""
        new_pl_norm = payment_link.lower() if is_setting_reference else ""
        is_changing_reference = is_setting_reference and (new_pl_norm != old_pl_norm)

        # Rule 1: Reference ID can only be set/changed when status is 'paid'
        if is_changing_reference and payment_status != "paid":
            raise ValueError(
                "Reference ID can only be entered when payment status is 'paid'."
            )

        # Rule 2: Reference ID must be unique across all leads (case-insensitive, trim-tolerant)
        if is_changing_reference:
            dup_lead_id = await self.find_lead_by_reference_id(payment_link, exclude_lead_id=lead_id)
            if dup_lead_id:
                raise ValueError(
                    f"Reference ID '{payment_link}' is already used by lead {dup_lead_id}."
                )

        # ----- BUILD UPDATE -----
        update_data = {
            "payment.status": payment_status,
            "payment.updated_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        if payment_link is not None:
            update_data["payment.payment_link"] = payment_link

        if amount is not None:
            update_data["payment.amount"] = amount

        # Generate Recon ID only when ALL conditions met:
        #   1. Lead does not already have a recon_id
        #   2. Payment status is 'paid'
        #   3. A Reference ID is being set on this lead (either now or already on the doc)
        effective_reference = payment_link if payment_link is not None else old_payment_link
        recon_id_assigned = None
        if (not old_payment.get('recon_id')
                and payment_status == "paid"
                and effective_reference):
            recon_id_assigned = await self._generate_recon_id()
            update_data["payment.recon_id"] = recon_id_assigned

        # Create audit entry
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "payment_update",
            "user": updated_by,
            "old_status": old_payment.get('status', 'pending'),
            "new_status": payment_status,
            "amount": amount,
            "payment_link": payment_link
        }
        if recon_id_assigned:
            audit_entry["recon_id_generated"] = recon_id_assigned

        # Update lead — catch DuplicateKeyError from the unique index on payment.payment_link
        # (race-condition guard). When two requests pass the read-then-write app check
        # in the same millisecond, the DB index rejects the second one.
        from pymongo.errors import DuplicateKeyError
        try:
            result = await self.db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$set": update_data,
                    "$push": {"audit_log": audit_entry}
                }
            )
        except DuplicateKeyError:
            # The index caught a concurrent duplicate that slipped past the app check
            raise ValueError(
                f"Reference ID '{payment_link}' is already used by another lead "
                f"(detected by database uniqueness constraint)."
            )

        return result.modified_count > 0

    async def update_invoice_number(self, lead_id: str, invoice_number: str, updated_by: str) -> bool:
        """
        Save/update the invoice number for a lead. Allowed ONLY when the lead's
        payment is 'paid' AND a Recon ID has already been generated. Editable
        (a later call overwrites the previous value). Audit-logged.

        Raises: ValueError on validation failure (caller maps to HTTP 400)
        """
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return False

        payment = lead.get('payment', {})
        if not is_paid(payment):
            raise ValueError("Invoice can only be added when payment status is 'paid'.")
        if not payment.get('recon_id'):
            raise ValueError("Invoice can only be added after a Recon ID has been generated.")

        invoice_number = (invoice_number or "").strip()
        if not invoice_number:
            raise ValueError("Invoice number cannot be empty.")

        old_invoice = payment.get('invoice_number')
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "invoice_updated" if old_invoice else "invoice_added",
            "user": updated_by,
            "old_value": old_invoice,
            "new_value": invoice_number,
        }
        result = await self.db.leads.update_one(
            {"lead_id": lead_id},
            {
                "$set": {"payment.invoice_number": invoice_number, "updated_at": datetime.utcnow()},
                "$push": {"audit_log": audit_entry}
            }
        )
        return result.modified_count > 0

    async def update_plan(
        self,
        lead_id: str,
        new_plan: str,
        updated_by: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Update the membership plan for a lead
        Args:
            lead_id: Lead ID
            new_plan: New plan (e.g., "1 Month", "3 Months", "6 Months", "12 Months")
            updated_by: User email who made the change
            reason: Optional reason for plan change
        Returns: True if updated, False if lead not found
        """
        # Get current lead
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return False

        # Block plan change on CLOSED leads
        if lead.get('status') == 'closed':
            raise ValueError(
                "Cannot change plan on a closed lead. "
                "Reopen the lead first by changing its status."
            )

        old_plan = lead.get('preferred_plan', '')

        # Create audit entry
        audit_entry = {
            "timestamp": datetime.utcnow(),
            "action": "plan_change",
            "user": updated_by,
            "old_value": old_plan,
            "new_value": new_plan,
            "reason": reason
        }

        # Update lead
        result = await self.db.leads.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "preferred_plan": new_plan,
                    "updated_at": datetime.utcnow()
                },
                "$push": {"audit_log": audit_entry}
            }
        )

        return result.modified_count > 0

    async def get_audit_trail(self, lead_id: str) -> Optional[List[Dict]]:
        """
        Get audit trail for a lead
        Args:
            lead_id: Lead ID
        Returns: List of audit entries or None if lead not found
        """
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            return None

        return lead.get('audit_log', [])

    def _format_lead(self, lead: Dict) -> Dict:
        """Format lead for API response"""
        formatted = lead.copy()
        formatted.pop('_id', None)
        # Legacy normalization: an earlier build set payment.status to 'completed'
        # after a confirmation email. 'completed' is not a valid status anywhere
        # else (it broke the payment modal on reopen), so surface it as 'paid'.
        pay = formatted.get('payment')
        if isinstance(pay, dict) and pay.get('status') == 'completed':
            pay['status'] = 'paid'
        return formatted


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points using Haversine formula

    Args:
        lat1, lon1: First point coordinates (degrees)
        lat2, lon2: Second point coordinates (degrees)

    Returns:
        Distance in kilometers (rounded to 2 decimals)
    """
    # Earth's radius in kilometers
    R = 6371.0

    # Convert degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Differences
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    # Haversine formula
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))

    # Distance
    distance = R * c

    return round(distance, 2)


def calculate_subscription_plans(base_monthly: int) -> Dict[str, Dict[str, int]]:
    """
    Calculate subscription plans with discounts

    Args:
        base_monthly: Base monthly price

    Returns:
        Dictionary with plan details
    """
    plans = {
        '1-month': {
            'duration': '1 month',
            'total': base_monthly,
            'monthly': base_monthly,
            'savings': 0,
            'discount': 0
        },
        '3-month': {
            'duration': '3 months',
            'total': int(base_monthly * 3 * 0.93),  # 7% discount
            'monthly': int(base_monthly * 0.93),
            'savings': int(base_monthly * 3 * 0.07),
            'discount': 7
        },
        '6-month': {
            'duration': '6 months',
            'total': int(base_monthly * 6 * 0.88),  # 12% discount
            'monthly': int(base_monthly * 0.88),
            'savings': int(base_monthly * 6 * 0.12),
            'discount': 12
        },
        '12-month': {
            'duration': '12 months',
            'total': int(base_monthly * 12 * 0.83),  # 17% discount
            'monthly': int(base_monthly * 0.83),
            'savings': int(base_monthly * 12 * 0.17),
            'discount': 17
        }
    }
    return plans
