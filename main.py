"""
Gym Habit - FastAPI Backend Server (MongoDB Version)
Demo Webapp
"""

from fastapi import FastAPI, HTTPException, Query, Form, Depends, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from contextlib import asynccontextmanager
import uvicorn
import os
import requests
from pathlib import Path
import csv
import io
from datetime import datetime, timedelta

from mongo_database import MongoGymDatabase, MongoLeadManager, calculate_subscription_plans, is_paid
from mongodb import MongoDB
from auth import create_access_token, get_current_user, verify_password
from email_service import email_service
import communications as comms
import config

# Initialize database managers
gym_db = MongoGymDatabase()
lead_manager = MongoLeadManager()


# ============================================================================
# LIFESPAN EVENTS
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events"""
    # Startup. A failure here must not crash the whole app: the pages should still
    # load and report the problem, rather than every request returning a blank 500.
    try:
        await MongoDB.connect_db()
        await gym_db.initialize()
        await lead_manager.initialize()
        await comms.seed_email_settings()
        print("[OK] MongoDB connection initialized")
    except Exception as exc:
        print(f"[ERROR] Startup failed to reach MongoDB: {exc}")
        print("[ERROR] Set MONGODB_URL (and MONGODB_DB_NAME) — see .env.example")

    yield

    # Shutdown
    try:
        await MongoDB.close_db()
        print("[OK] MongoDB connection closed")
    except Exception:
        pass


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Gym Habit API",
    description="Partner Gym Finder for Demo Webapp",
    version="2.0.0",
    lifespan=lifespan
)

# GZip responses (big win for the large /api/gyms JSON and the HTML pages)
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: ["https://example.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths are resolved from this file, not the working directory, so the app also
# runs where the CWD differs (e.g. a serverless function unpacked into /var/task).
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Mount static files
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ============================================================================
# RBAC HELPERS
# Two roles only: 'admin' (full access) and 'agent' (lead work on OWN leads).
# Agents cannot: delete anything, view audit logs, add/edit/delete gyms or
# partners, or manage users. Agents may only modify leads assigned to them.
# ============================================================================

def is_admin(current_user: dict) -> bool:
    """True if the current user is an admin."""
    return current_user.get('role') == 'admin'


def ensure_admin(current_user: dict):
    """Raise 403 unless the current user is an admin."""
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")


async def ensure_lead_access(lead_id: str, current_user: dict) -> dict:
    """
    Authorize a write/action on a lead and return the (fresh) lead doc.

    Rules:
      - Admin: always allowed; viewing/acting does NOT change ownership.
      - Agent: allowed only if the lead is already assigned to them. Leads are
               auto-assigned at creation (round-robin), so an agent never claims
               by acting. Forbidden (403) if owned by another agent or unassigned.
    """
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    if is_admin(current_user):
        return lead

    owner = lead.get('assigned_to')
    if not owner or owner != current_user.get('email'):
        detail = (
            f"This lead is assigned to {owner}. Only the assigned agent or an admin can modify it."
            if owner else
            "This lead is not assigned to you. Only an admin can act on unassigned leads."
        )
        raise HTTPException(status_code=403, detail=detail)
    return lead


# ============================================================================
# HELPER FUNCTIONS - LOCATION SEARCH
# ============================================================================

def is_pincode(search_text: str) -> bool:
    """Check if input is a 6-digit Indian pincode"""
    cleaned = search_text.strip()
    return cleaned.isdigit() and len(cleaned) == 6


def geocode_location(location_text: str) -> dict:
    """
    Convert location text to lat/lon using Google Geocoding API

    Args:
        location_text: City, town, or area (e.g., "Andheri Mumbai")

    Returns:
        {
            "lat": 19.1136,
            "lon": 72.8697,
            "formatted_address": "Andheri West, Mumbai, Maharashtra, India",
            "city": "Mumbai"
        }
    """
    if not config.GOOGLE_GEOCODING_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Google Geocoding API key not configured"
        )

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": location_text,
        "key": config.GOOGLE_GEOCODING_API_KEY,
        "region": "in",  # Bias results to India
        "components": "country:IN"  # Restrict to India only
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()

        if data['status'] == 'OK' and len(data['results']) > 0:
            result = data['results'][0]
            location = result['geometry']['location']

            # Extract city from address components
            city = None
            for component in result.get('address_components', []):
                if 'locality' in component['types']:
                    city = component['long_name']
                    break
                elif 'administrative_area_level_2' in component['types']:
                    city = component['long_name']

            return {
                "lat": location['lat'],
                "lon": location['lng'],
                "formatted_address": result['formatted_address'],
                "city": city
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Location not found: {location_text}"
            )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error calling Google Geocoding API: {str(e)}"
        )


# ============================================================================
# PYDANTIC MODELS FOR REQUEST VALIDATION
# ============================================================================

class SubscriptionRequest(BaseModel):
    """Subscription form data"""
    gym_id: int
    gym_name: str
    partner_name: str
    center_code: Optional[str] = None  # NEW: Center code for admin/support
    center_type: Optional[str] = None  # NEW: Center type (GX, Cult Center, etc.)
    full_name: str
    email: Optional[EmailStr] = ""
    phone: str
    preferred_plan: str  # NEW format: "Cultpass Elite | 3 Months"
    plan_price: Optional[float] = None  # NEW: Selected plan price
    billing_address: str
    message: Optional[str] = ""
    user_latitude: Optional[float] = None
    user_longitude: Optional[float] = None
    user_city: Optional[str] = None

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        """Validate 10-digit Indian phone number"""
        if not v.isdigit() or len(v) != 10:
            raise ValueError('Phone must be 10 digits')
        if not v[0] in '6789':
            raise ValueError('Phone must start with 6, 7, 8, or 9')
        return v

    @field_validator('full_name')
    @classmethod
    def validate_name(cls, v):
        """Validate name length"""
        if len(v) < 3:
            raise ValueError('Name must be at least 3 characters')
        if len(v) > 100:
            raise ValueError('Name must be less than 100 characters')
        return v.strip()

    @field_validator('preferred_plan')
    @classmethod
    def validate_plan(cls, v):
        """Validate plan selection - accepts dynamic plan names"""
        if not v or len(v) < 2:
            raise ValueError('Plan selection is required')
        return v.strip()


class LoginRequest(BaseModel):
    """Login request"""
    email: EmailStr
    password: str


class GymCreateRequest(BaseModel):
    """Request model for creating a new gym"""
    gym_name: str
    partner_name: str
    address: str
    city: str
    state: str
    pincode: str
    latitude: float
    longitude: float
    amenities: list[str]
    subscription_amount: Optional[int] = 1499
    icon: Optional[str] = None  # Emoji or base64 image
    custom_plans: Optional[dict] = None  # Custom pricing for 1_month, 3_months, 6_months, 12_months

    @field_validator('pincode')
    @classmethod
    def validate_pincode(cls, v):
        """Validate 6-digit pincode"""
        if not v.isdigit() or len(v) != 6:
            raise ValueError('Pincode must be 6 digits')
        return v

    @field_validator('gym_name', 'partner_name', 'city', 'state')
    @classmethod
    def validate_non_empty(cls, v):
        """Validate non-empty strings"""
        if not v or len(v.strip()) == 0:
            raise ValueError('Field cannot be empty')
        return v.strip()


class PartnerCreateRequest(BaseModel):
    """Request model for creating a new partner"""
    name: str
    description: Optional[str] = ""
    icon: Optional[str] = None  # Emoji or base64 image

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Validate partner name"""
        if not v or len(v.strip()) == 0:
            raise ValueError('Partner name cannot be empty')
        if len(v) > 100:
            raise ValueError('Partner name must be less than 100 characters')
        return v.strip()


# ============================================================================
# FRONTEND ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve main user page"""
    try:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
    except:
        return HTMLResponse("<h1>Frontend not found. Please build frontend first.</h1>")


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    """Serve admin panel"""
    try:
        return FileResponse(str(FRONTEND_DIR / "admin.html"))
    except:
        return HTMLResponse("<h1>Admin panel not found.</h1>")


# ============================================================================
# API ENDPOINTS - PUBLIC
# ============================================================================

@app.get("/api/partners")
async def get_partners():
    """
    Get list of all gym partners with counts
    Returns: {"partners": [{"name": "Cult", "count": 10}], "total": 5}
    """
    partners = await gym_db.get_all_partners()
    return {
        "partners": partners,
        "total": len(partners)
    }


@app.get("/api/gyms")
async def get_gyms(partner: Optional[str] = None):
    """
    Get all gyms, optionally filtered by partner
    Query params:
        partner (optional): Filter by partner name
    """
    if partner:
        gyms = await gym_db.get_gyms_by_partner(partner)
        return {
            "gyms": gyms,
            "total": len(gyms),
            "partner": partner
        }
    else:
        gyms = await gym_db.get_all_gyms()
        return {
            "gyms": gyms,
            "total": len(gyms)
        }


@app.get("/api/gyms/nearby")
async def get_nearby_gyms(
    lat: float = Query(..., description="User latitude"),
    lon: float = Query(..., description="User longitude"),
    partner: Optional[str] = Query(None, description="Filter by partner"),
    limit: int = Query(10, ge=1, le=50, description="Max results")
):
    """
    Find nearest gyms based on user location
    Query params:
        lat: User's latitude
        lon: User's longitude
        partner (optional): Filter by partner name
        limit (optional): Max number of results (default: 10)
    """
    gyms = await gym_db.get_nearby_gyms(lat, lon, partner=partner, limit=limit)

    return {
        "gyms": gyms,
        "total": len(gyms),
        "user_location": {"latitude": lat, "longitude": lon}
    }


@app.get("/api/gyms/search-by-location")
async def search_gyms_by_location(
    location: str = Query(..., description="City, area, or 6-digit pincode"),
    partner: Optional[str] = Query(None, description="Filter by partner"),
    limit: int = Query(20, ge=1, le=50, description="Max results")
):
    """
    Search gyms by location text or pincode (optimized for iframe use)

    Supports three search modes:
    1. Pincode (6 digits): Instant search using pincode index
    2. Text location: Uses Google Geocoding API + geospatial search
    3. City name: Direct city filtering + distance sort

    Query params:
        location: "400053" OR "Andheri Mumbai" OR "Mumbai"
        partner (optional): Filter by partner name
        limit (optional): Max number of results (default: 20)

    Returns:
        {
            "gyms": [...],
            "total": 10,
            "search_type": "pincode" | "geocoded" | "city",
            "location": "Formatted address or pincode",
            "coordinates": {"lat": 19.11, "lon": 72.86}
        }
    """
    location_clean = location.strip()

    # MODE 1: Pincode Search (Instant, no API call)
    if is_pincode(location_clean):
        gyms = await gym_db.search_by_pincode(location_clean, limit=limit)

        # Apply partner filter if provided
        if partner:
            gyms = [g for g in gyms if g['partner_name'].lower() == partner.lower()]

        return {
            "gyms": gyms[:limit],
            "total": len(gyms),
            "search_type": "pincode",
            "location": f"Pincode {location_clean}",
            "coordinates": None
        }

    # MODE 2: Text Location Search.
    # Geocoding needs a Google API key. When none is configured (the default for
    # this demo) fall back to matching the text against the gym catalogue itself,
    # so city and area search keeps working without any external service.
    if not config.GOOGLE_GEOCODING_API_KEY:
        gyms = await gym_db.search_by_text(location_clean, partner=partner, limit=limit)
        return {
            "gyms": gyms,
            "total": len(gyms),
            "search_type": "local",
            "location": location_clean.title(),
            "coordinates": None
        }

    try:
        geocode_result = geocode_location(location_clean)

        # Use geospatial search without city filter for better coverage
        gyms = await gym_db.get_nearby_gyms(
            user_lat=geocode_result['lat'],
            user_lon=geocode_result['lon'],
            partner=partner,
            city=None,  # Don't filter by city, rely on distance only
            limit=limit
        )

        return {
            "gyms": gyms,
            "total": len(gyms),
            "search_type": "geocoded",
            "location": geocode_result['formatted_address'],
            "coordinates": {
                "lat": geocode_result['lat'],
                "lon": geocode_result['lon']
            }
        }
    except HTTPException:
        # If geocoding fails, return empty result
        raise


@app.get("/api/gyms/{gym_id}")
async def get_gym_details(gym_id: int):
    """
    Get detailed information about a specific gym
    Path param:
        gym_id: Gym ID
    """
    gym = await gym_db.get_gym_by_id(gym_id)

    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")

    # Calculate subscription plans - NEW: use plans array, fallback to custom_plans, or auto-calculate
    if gym.get('plans') and len(gym['plans']) > 0:
        # NEW: Use plans array from CSV upload
        plans_list = gym['plans']  # List of {plan_name, mrp, discount, price}
        # Return as list for frontend to render dynamically
        response = gym.copy()
        response['subscription_plans_list'] = plans_list
        # Also return amenities as list
        amenities_list = gym.get('amenities', [])
        if isinstance(amenities_list, str):
            amenities_list = [a.strip() for a in amenities_list.split(',')]
        response['amenities_list'] = amenities_list
    elif gym.get('custom_plans'):
        # OLD: Use custom plans and calculate derived values (legacy support)
        plans = {}
        custom = gym['custom_plans']

        for key, total in custom.items():
            duration_map = {'1_month': 1, '3_months': 3, '6_months': 6, '12_months': 12}
            months = duration_map.get(key, 1)
            duration_text = f"{months} month{'s' if months > 1 else ''}"

            # Calculate monthly rate and savings based on base price
            base_price = gym['subscription_amount']
            expected_total = base_price * months
            savings = expected_total - total
            monthly = total // months
            discount = int((savings / expected_total) * 100) if expected_total > 0 else 0

            plans[key.replace('_', '-')] = {
                'duration': duration_text,
                'total': total,
                'monthly': monthly,
                'savings': max(0, savings),
                'discount': discount
            }

        # Amenities are now always a list (from _format_gym). Pass through.
        amenities_value = gym.get('amenities', [])
        if isinstance(amenities_value, list):
            amenities_list = amenities_value
        elif isinstance(amenities_value, str):
            sep = '•' if '•' in amenities_value else ','
            amenities_list = [a.strip() for a in amenities_value.split(sep) if a.strip()]
        else:
            amenities_list = []

        response = gym.copy()
        response['subscription_plans'] = plans
        response['amenities_list'] = amenities_list
    else:
        # Auto-calculate plans based on base price (legacy)
        base_price = gym['subscription_amount']
        plans = calculate_subscription_plans(base_price)

        amenities_value = gym.get('amenities', [])
        if isinstance(amenities_value, list):
            amenities_list = amenities_value
        elif isinstance(amenities_value, str):
            sep = '•' if '•' in amenities_value else ','
            amenities_list = [a.strip() for a in amenities_value.split(sep) if a.strip()]
        else:
            amenities_list = []

        response = gym.copy()
        response['subscription_plans'] = plans
        response['amenities_list'] = amenities_list

    return response


@app.post("/api/subscription/request")
async def submit_subscription_request(request: SubscriptionRequest):
    """
    Submit subscription inquiry form
    Body: SubscriptionRequest model
    Auto-triggers LEAD_ACKNOWLEDGEMENT email
    """
    try:
        # Validate gym exists
        gym = await gym_db.get_gym_by_id(request.gym_id)
        if not gym:
            raise HTTPException(status_code=404, detail="Gym not found")

        # Round-robin auto-assignment: pick the next active agent (admin fallback if none)
        assignee = await lead_manager.pick_next_assignee()

        # Save lead (created already owned by the chosen assignee)
        lead_id = await lead_manager.save_lead(request.dict(), assignee=assignee)

        # Auto-trigger: Send acknowledgement email (CC list is admin-managed)
        email_result = {"sent": False}
        if request.email:
            email_result = email_service.send_lead_acknowledgement(
                customer_email=request.email,
                customer_name=request.full_name,
                gym_name=request.gym_name,
                cc=await comms.get_cc_list("LEAD_ACKNOWLEDGEMENT")
            )
            await comms.log_communication(
                lead={"lead_id": lead_id, "full_name": request.full_name, "email": request.email},
                email_type="LEAD_ACKNOWLEDGEMENT", trigger="auto",
                sent_by="system", result=email_result
            )

        return {
            "success": True,
            "message": "Thank you! Our wellness team will contact you within 24 hours to help you start your fitness journey.",
            "lead_id": lead_id,
            "email_sent": email_result.get("success", False)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API ENDPOINTS - AUTHENTICATION
# ============================================================================

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """
    Admin/Facilitator login with JWT
    Body: {"email": "admin@example.com", "password": "Demo@12345"}
    Returns: {"access_token": "...", "user": {...}}
    """
    # Find user
    user = await MongoDB.db.users.find_one({"email": request.email})

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(request.password, user['password_hash']):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Check if user is active
    if not user.get('is_active', False):
        raise HTTPException(
            status_code=403,
            detail="Account is inactive. Please contact administrator."
        )

    # Create JWT token
    token_data = {
        "user_id": str(user['_id']),
        "email": user['email'],
        "role": user['role'],
        "name": user['name']
    }
    access_token = create_access_token(token_data)

    # Update last login
    from datetime import datetime
    await MongoDB.db.users.update_one(
        {"_id": user['_id']},
        {
            "$set": {"last_login": datetime.utcnow()},
            "$inc": {"login_count": 1}
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user['email'],
            "name": user['name'],
            "role": user['role']
        }
    }


@app.get("/api/auth/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    Get current logged-in user information
    Requires JWT authentication
    """
    # Fetch full user details from database
    user = await MongoDB.db.users.find_one({"email": current_user['email']})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "email": user['email'],
        "name": user['name'],
        "role": user['role'],
        "is_active": user.get('is_active', True),
        "created_at": user.get('created_at'),
        "last_login": user.get('last_login'),
        "login_count": user.get('login_count', 0)
    }


@app.post("/api/auth/change-password")
async def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Change user password
    Requires JWT authentication and current password verification
    """
    # Validate new password
    if len(new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="New password must be at least 8 characters long"
        )

    # Get user from database
    user = await MongoDB.db.users.find_one({"email": current_user['email']})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify old password
    if not verify_password(old_password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # Hash new password
    from auth import hash_password
    new_password_hash = hash_password(new_password)

    # Update password
    await MongoDB.db.users.update_one(
        {"email": current_user['email']},
        {
            "$set": {
                "password_hash": new_password_hash,
                "password_updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Password changed successfully"}


@app.post("/api/auth/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout endpoint (optional - mostly for client-side token cleanup)
    In stateless JWT, logout is handled client-side by removing the token
    This endpoint can be used for audit logging
    """
    # Log logout event (optional)
    await MongoDB.db.users.update_one(
        {"email": current_user['email']},
        {"$set": {"last_logout": datetime.utcnow()}}
    )

    return {"message": "Logged out successfully"}


# ============================================================================
# API ENDPOINTS - ADMIN (Protected)
# ============================================================================

# Leads are stored with UTC created_at but the portal displays IST, so date
# filters must mean IST calendar days (inclusive on both ends). Used by both
# the leads table and the CSV export so their row sets always match.
IST_OFFSET = timedelta(hours=5, minutes=30)

def parse_ist_date_range(from_date: Optional[str], to_date: Optional[str]):
    date_from = None
    date_to = None
    if from_date:
        try:
            date_from = datetime.strptime(from_date, "%Y-%m-%d") - IST_OFFSET
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
    if to_date:
        try:
            # end of the To day in IST: start of the next IST day, minus 1µs ($lte)
            date_to = (datetime.strptime(to_date, "%Y-%m-%d")
                       + timedelta(days=1) - IST_OFFSET - timedelta(microseconds=1))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
    return date_from, date_to


@app.get("/api/admin/leads")
async def get_leads(
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None)
):
    """
    Get all leads with filters (admin/facilitator only)
    Requires JWT authentication
    """
    date_from, date_to = parse_ist_date_range(from_date, to_date)

    # Calculate skip
    skip = (page - 1) * per_page

    # Get leads
    result = await lead_manager.get_all_leads(
        skip=skip,
        limit=per_page,
        status_filter=status,
        payment_status_filter=payment_status,
        city_filter=city,
        assigned_to_filter=assigned_to,
        date_from=date_from,
        date_to=date_to
    )

    return result


@app.get("/api/admin/stats")
async def get_admin_stats(current_user: dict = Depends(get_current_user)):
    """
    Get admin dashboard statistics
    Requires JWT authentication
    """
    # Count leads by status
    pipeline_status = [
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }
        }
    ]
    status_counts = await MongoDB.db.leads.aggregate(pipeline_status).to_list(None)

    # Count leads by payment status
    pipeline_payment = [
        {
            "$group": {
                "_id": "$payment.status",
                "count": {"$sum": 1}
            }
        }
    ]
    payment_counts = await MongoDB.db.leads.aggregate(pipeline_payment).to_list(None)

    # Total gyms
    total_gyms = await MongoDB.db.gyms.count_documents({"is_active": True})

    # Total leads
    total_leads = await MongoDB.db.leads.count_documents({})

    return {
        "total_leads": total_leads,
        "total_gyms": total_gyms,
        "status_breakdown": {item['_id']: item['count'] for item in status_counts},
        "payment_breakdown": {item['_id']: item['count'] for item in payment_counts}
    }


@app.get("/api/admin/leads/{lead_id}")
async def get_lead_details(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get detailed information for a specific lead.
    Requires JWT authentication.
    Viewing rule:
      - Any authenticated user may VIEW any lead (read-only).
      - Viewing never changes ownership. Acting (write endpoints) is gated by
        ensure_lead_access: agents may only modify leads assigned to them.
    """
    lead = await lead_manager.get_lead_by_id(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return lead


@app.patch("/api/admin/leads/{lead_id}/status")
async def update_lead_status_endpoint(
    lead_id: str,
    status: str = Form(...),
    reason: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Update lead status
    Valid statuses: new, contacted, interested, not_interested, closed
    """
    valid_statuses = ["new", "contacted", "interested", "not_interested", "closed", "activated"]

    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    try:
        success = await lead_manager.update_lead_status(
            lead_id=lead_id,
            new_status=status,
            updated_by=current_user['email'],
            reason=reason
        )
    except ValueError as ve:
        # Locked-after-paid rule
        raise HTTPException(status_code=400, detail=str(ve))

    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"message": "Status updated successfully", "lead_id": lead_id, "new_status": status}


@app.post("/api/admin/leads/{lead_id}/comments")
async def add_comment_endpoint(
    lead_id: str,
    comment: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Add a comment to a lead
    """
    if not comment or len(comment.strip()) == 0:
        raise HTTPException(status_code=400, detail="Comment cannot be empty")

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    success = await lead_manager.add_comment(
        lead_id=lead_id,
        comment_text=comment,
        added_by=current_user['email']
    )

    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"message": "Comment added successfully", "lead_id": lead_id}


@app.patch("/api/admin/leads/{lead_id}/payment")
async def update_payment_endpoint(
    lead_id: str,
    payment_status: str = Form(...),
    payment_link: Optional[str] = Form(None),
    amount: Optional[int] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Update payment information for a lead
    Valid payment statuses: pending, link_shared, paid, failed
    """
    valid_payment_statuses = ["pending", "link_shared", "paid", "failed"]

    if payment_status not in valid_payment_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid payment status. Must be one of: {', '.join(valid_payment_statuses)}"
        )

    # Bounds check on payment amount: must be > 0 and ≤ ₹10 lakh
    # Razorpay also rejects negative & zero — protect at app layer for clearer errors.
    PAYMENT_AMOUNT_MAX = 1_000_000  # 10 lakh INR — reasonable upper bound for any gym membership
    if amount is not None:
        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Payment amount must be greater than 0. Got: {amount}"
            )
        if amount > PAYMENT_AMOUNT_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Payment amount exceeds maximum (₹{PAYMENT_AMOUNT_MAX:,}). Got: ₹{amount:,}"
            )

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    try:
        success = await lead_manager.update_payment(
            lead_id=lead_id,
            payment_status=payment_status,
            updated_by=current_user['email'],
            payment_link=payment_link,
            amount=amount
        )
    except ValueError as ve:
        # Validation errors (Reference ID rules) → 400 Bad Request
        raise HTTPException(status_code=400, detail=str(ve))

    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {
        "message": "Payment updated successfully",
        "lead_id": lead_id,
        "payment_status": payment_status
    }


@app.get("/api/admin/recon-preview")
async def recon_preview_endpoint(
    reference_id: Optional[str] = Query(None, description="Reference ID (Razorpay txn ID) to validate"),
    lead_id: Optional[str] = Query(None, description="Lead ID being edited (excluded from duplicate check)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Preview the next Recon ID and validate Reference ID uniqueness — no DB writes.
    Used by the admin UI to give live feedback as the user types the Reference ID.

    Returns:
        {
          "predicted_recon_id": "HHGYM-XXXXX",     # what would be assigned on save
          "is_duplicate": false,                    # true if reference_id is taken by another lead
          "duplicate_lead_id": null                 # lead_id of the conflicting lead (if any)
        }
    """
    # If a lead already has a recon_id, return that one (preview = existing)
    existing_recon = None
    if lead_id:
        existing_lead = await MongoDB.db.leads.find_one({"lead_id": lead_id})
        if existing_lead:
            existing_recon = existing_lead.get("payment", {}).get("recon_id")

    # Check duplicate (only meaningful if reference_id provided)
    duplicate_lead_id = None
    if reference_id:
        duplicate_lead_id = await lead_manager.find_lead_by_reference_id(
            reference_id=reference_id,
            exclude_lead_id=lead_id
        )

    # Predicted recon ID = existing one (if any) else peek next from counter
    if existing_recon:
        predicted = existing_recon
    else:
        predicted = await lead_manager.peek_next_recon_id()

    return {
        "predicted_recon_id": predicted,
        "is_existing": existing_recon is not None,
        "is_duplicate": duplicate_lead_id is not None,
        "duplicate_lead_id": duplicate_lead_id
    }


@app.patch("/api/admin/leads/{lead_id}/plan")
async def update_plan_endpoint(
    lead_id: str,
    new_plan: str = Form(...),
    reason: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Update the membership plan for a lead.
    Rules:
      - Cannot change plan when payment.status == 'paid'
      - new_plan must be one of the gym's available plans
        (matches against subscription_plans_list[].plan_name if present,
         else falls back to "1 Month" / "3 Months" / "6 Months" / "12 Months")
    """
    # 1. Fetch the lead
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    # 2. Block if payment is already paid
    if is_paid(lead.get("payment")):
        raise HTTPException(
            status_code=400,
            detail="Cannot change plan after payment is marked as 'paid'."
        )

    # 3. Look up the gym to get its actual available plans
    gym_id = lead.get("gym_id")
    gym = await gym_db.get_gym_by_id(gym_id) if gym_id else None
    if not gym:
        raise HTTPException(status_code=400, detail="Gym not found for this lead.")

    # 4. Build the valid plan list:
    #    - Modern gyms store named plans (like "Cultpass Elite | 12 Months") in `plans`;
    #      `subscription_plans_list` only exists as a computed field in the
    #      /api/gyms/{gym_id} response, never on the stored doc.
    #    - Legacy gyms only have `subscription_amount` → use the 4 standard duration labels
    valid_plans: list = []
    spl = gym.get("plans") or gym.get("subscription_plans_list")
    if spl and isinstance(spl, list) and len(spl) > 0:
        valid_plans = [p["plan_name"] for p in spl if p.get("plan_name")]
    else:
        valid_plans = ["1 Month", "3 Months", "6 Months", "12 Months"]

    if new_plan not in valid_plans:
        raise HTTPException(
            status_code=400,
            detail=f"Plan '{new_plan}' is not available for this gym. Valid options: {valid_plans}"
        )

    # 5. Persist
    try:
        success = await lead_manager.update_plan(
            lead_id=lead_id,
            new_plan=new_plan,
            updated_by=current_user['email'],
            reason=reason
        )
    except ValueError as ve:
        # Closed-lead block, etc.
        raise HTTPException(status_code=400, detail=str(ve))

    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"message": "Plan updated successfully", "lead_id": lead_id, "new_plan": new_plan}


@app.get("/api/admin/leads/{lead_id}/audit")
async def get_audit_trail_endpoint(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get audit trail for a lead (admin only).
    Returns all changes made to the lead.
    """
    ensure_admin(current_user)

    audit_trail = await lead_manager.get_audit_trail(lead_id)

    if audit_trail is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"lead_id": lead_id, "audit_trail": audit_trail}


@app.patch("/api/admin/leads/{lead_id}/assign")
async def reassign_lead_endpoint(
    lead_id: str,
    assignee_email: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Reassign a lead to a specific agent/admin (admin only).
    Used to move a lead between support agents (e.g. someone on leave).
    """
    ensure_admin(current_user)

    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    # Assignee must be an existing, active user
    assignee = await MongoDB.db.users.find_one({"email": assignee_email})
    if not assignee:
        raise HTTPException(status_code=404, detail=f"User {assignee_email} not found")
    if not assignee.get("is_active", False):
        raise HTTPException(status_code=400, detail=f"User {assignee_email} is inactive")

    success = await lead_manager.reassign_lead(
        lead_id=lead_id,
        assignee_email=assignee_email,
        assignee_name=assignee.get("name", assignee_email),
        changed_by=current_user['email']
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"message": "Lead reassigned successfully", "lead_id": lead_id, "assigned_to": assignee_email}


# ============================================================================
# API ENDPOINTS - EMAIL TRIGGERS (Admin/Support Manual Triggers)
# ============================================================================

class EmailTriggerRequest(BaseModel):
    """Request model for manual email triggers"""
    lead_id: str
    transaction_id: Optional[str] = None  # For payment confirmation
    amount: Optional[float] = None  # For payment confirmation


# ─────────────────────────────────────────────────────────────────────────
# EMAIL RATE LIMIT
#   Rule:  At most 1 email of each type per lead per UTC day,
#          AND no more than 8 emails per lead per UTC day in total.
#   Storage: lead.email_log = [{type, sent_at (utc), user}, ...]
# ─────────────────────────────────────────────────────────────────────────
EMAIL_DAILY_TOTAL_CAP = 8


async def check_and_record_email_send(lead_id: str, email_type: str, user_email: str) -> None:
    """
    Read lead.email_log, check today's sends, and record this attempt.
    Raises HTTPException(429) when rate limit is exceeded.
    Recording happens BEFORE the actual SendGrid call so a click counts
    toward the daily quota even if SendGrid is misconfigured (avoids
    silent retry-spam if the agent keeps clicking).
    """
    lead = await MongoDB.db.leads.find_one({"lead_id": lead_id})
    if not lead:
        # Caller already checks this; left here as a safety net.
        raise HTTPException(status_code=404, detail="Lead not found")

    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)

    log = lead.get("email_log", []) or []
    today = [
        e for e in log
        if isinstance(e.get("sent_at"), datetime) and e["sent_at"] >= today_start
    ]

    # Per-type daily cap: at most 1 of each type per day
    same_type_today = [e for e in today if e.get("type") == email_type]
    if same_type_today:
        last = same_type_today[-1]
        last_ts = last["sent_at"].strftime("%Y-%m-%d %H:%M UTC")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit: a '{email_type}' email was already sent to this lead today "
                f"at {last_ts}. Only one of each email type per customer per day is allowed."
            )
        )

    # Total daily cap
    if len(today) >= EMAIL_DAILY_TOTAL_CAP:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit: this lead has already received {len(today)} emails today. "
                f"Maximum {EMAIL_DAILY_TOTAL_CAP} emails per customer per day."
            )
        )

    # Record this send attempt
    await MongoDB.db.leads.update_one(
        {"lead_id": lead_id},
        {"$push": {"email_log": {"type": email_type, "sent_at": now, "user": user_email}}}
    )


@app.post("/api/admin/leads/{lead_id}/invoice")
async def update_invoice_endpoint(
    lead_id: str,
    invoice_number: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Save/update the invoice number for a lead.
    Allowed only when payment is 'paid' AND a Recon ID exists. Editable.
    """
    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    try:
        success = await lead_manager.update_invoice_number(
            lead_id=lead_id,
            invoice_number=invoice_number,
            updated_by=current_user['email']
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if not success:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return {"message": "Invoice number saved successfully", "lead_id": lead_id}


@app.post("/api/admin/leads/{lead_id}/email/no-response")
async def send_no_response_email(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    NO_RESPONSE_FOLLOWUP - Send when customer doesn't answer call
    Triggered by: Admin/Support CTA
    """
    # Get lead details
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not lead.get("email"):
        raise HTTPException(status_code=400, detail="Lead has no email address")

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    # Rate limit (1/type/day, 8/day total)
    await check_and_record_email_send(lead_id, "NO_RESPONSE_FOLLOWUP", current_user.get("email", "agent"))

    # Send email (CC list is admin-managed)
    result = email_service.send_no_response_followup(
        customer_email=lead["email"],
        customer_name=lead.get("full_name", "Customer"),
        gym_name=lead.get("gym_name", "Demo Webapp Gym"),
        cc=await comms.get_cc_list("NO_RESPONSE_FOLLOWUP")
    )
    await comms.log_communication(lead, "NO_RESPONSE_FOLLOWUP", "manual",
                                  current_user.get("email", "agent"), result)

    # Log action in audit trail
    if result.get("success"):
        await lead_manager.add_comment(
            lead_id=lead_id,
            comment_text=f"No Response Follow-up email sent by {current_user.get('name', 'Agent')}",
            added_by=current_user.get("email", "agent")
        )

    return {
        "success": result.get("success", False),
        "message": "Follow-up email sent successfully" if result.get("success") else result.get("error"),
        "email_type": "NO_RESPONSE_FOLLOWUP"
    }


@app.post("/api/admin/leads/{lead_id}/email/payment-confirmation")
async def send_payment_confirmation_email(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    PAYMENT_CONFIRMATION - Send after payment is validated
    Triggered by: Admin/Support CTA
    """
    # Get lead details
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not lead.get("email"):
        raise HTTPException(status_code=400, detail="Lead has no email address")

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    # Strict flow: payment must already be marked 'paid' before this email can go out.
    # Sending this email never changes payment status — the agent/admin must mark it Paid first.
    if not is_paid(lead.get("payment")):
        raise HTTPException(
            status_code=400,
            detail="Payment must be marked 'Paid' before sending the payment confirmation email."
        )

    # Rate limit (1/type/day, 8/day total)
    await check_and_record_email_send(lead_id, "PAYMENT_CONFIRMATION", current_user.get("email", "agent"))

    # Get amount from lead's payment info or plan
    amount = lead.get("payment", {}).get("amount") or lead.get("plan_price") or 0

    # Send email (CC list is admin-managed)
    result = email_service.send_payment_confirmation(
        customer_email=lead["email"],
        customer_name=lead.get("full_name", "Customer"),
        gym_name=lead.get("gym_name", "Demo Webapp Gym"),
        amount=amount,
        transaction_id=lead.get("lead_id", "N/A"),
        plan_name=lead.get("preferred_plan", "Gym Package"),
        cc=await comms.get_cc_list("PAYMENT_CONFIRMATION")
    )
    await comms.log_communication(lead, "PAYMENT_CONFIRMATION", "manual",
                                  current_user.get("email", "agent"), result)

    # Log action only. Do NOT change payment status here — it stays 'paid'.
    # (An earlier build set it to 'completed', which is not a valid status and
    # blanked out the payment modal/detail on reopen.)
    if result.get("success"):
        await lead_manager.add_comment(
            lead_id=lead_id,
            comment_text=f"Payment confirmation email sent by {current_user.get('name', 'Agent')}",
            added_by=current_user.get("email", "agent")
        )

    return {
        "success": result.get("success", False),
        "message": "Payment confirmation email sent successfully" if result.get("success") else result.get("error"),
        "email_type": "PAYMENT_CONFIRMATION"
    }


@app.post("/api/admin/leads/{lead_id}/email/closure")
async def send_closure_email(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    NO_INTEREST_CLOSURE - Send to close inactive leads
    Triggered by: Admin/Support CTA
    """
    # Get lead details
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not lead.get("email"):
        raise HTTPException(status_code=400, detail="Lead has no email address")

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    # Rate limit (1/type/day, 8/day total)
    await check_and_record_email_send(lead_id, "NO_INTEREST_CLOSURE", current_user.get("email", "agent"))

    # Send email (CC list is admin-managed)
    result = email_service.send_no_interest_closure(
        customer_email=lead["email"],
        customer_name=lead.get("full_name", "Customer"),
        gym_name=lead.get("gym_name", "Demo Webapp Gym"),
        cc=await comms.get_cc_list("NO_INTEREST_CLOSURE")
    )
    await comms.log_communication(lead, "NO_INTEREST_CLOSURE", "manual",
                                  current_user.get("email", "agent"), result)

    # Log action and update status to closed
    if result.get("success"):
        await lead_manager.update_lead_status(
            lead_id=lead_id,
            new_status="closed",
            updated_by=current_user.get("email", "agent"),
            reason="No Interest - Closure email sent"
        )
        await lead_manager.add_comment(
            lead_id=lead_id,
            comment_text=f"Lead closed - No Interest closure email sent by {current_user.get('name', 'Agent')}",
            added_by=current_user.get("email", "agent")
        )

    return {
        "success": result.get("success", False),
        "message": "Closure email sent and lead marked as closed" if result.get("success") else result.get("error"),
        "email_type": "NO_INTEREST_CLOSURE"
    }


@app.post("/api/admin/leads/{lead_id}/email/interim-info")
async def send_interim_info_email(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    INTERIM_INFO - Send transaction details to customer after payment is marked 'paid'.
    Mandatory checks:
      - Payment status must be 'paid'
      - Lead must have an email address on record
    Triggered by: Admin/Support CTA "Send Interim Info"
    """
    # Get lead details
    lead = await lead_manager.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Mandatory check 1: Payment status must be 'paid'
    payment = lead.get("payment", {}) or {}
    if not is_paid(payment):
        raise HTTPException(
            status_code=400,
            detail="Cannot send Interim Info — payment status must be 'paid'."
        )

    # Mandatory check 2: Lead must have an email
    if not lead.get("email"):
        raise HTTPException(
            status_code=400,
            detail="Cannot send Interim Info — lead has no email address on record."
        )

    # Ownership: agents may only act on their own (or unassigned) leads.
    await ensure_lead_access(lead_id, current_user)

    # Rate limit (1/type/day, 8/day total)
    await check_and_record_email_send(lead_id, "INTERIM_INFO", current_user.get("email", "agent"))

    # Send email (CC list is admin-managed)
    result = email_service.send_interim_info(
        customer_email=lead["email"],
        customer_name=lead.get("full_name", "Customer"),
        reference_id=payment.get("payment_link") or "N/A",
        transaction_amount=payment.get("amount"),
        plan_name=lead.get("preferred_plan", "Gym Package"),
        cc=await comms.get_cc_list("INTERIM_INFO")
    )
    await comms.log_communication(lead, "INTERIM_INFO", "manual",
                                  current_user.get("email", "agent"), result)

    # Log action to audit trail / comments
    if result.get("success"):
        await lead_manager.add_comment(
            lead_id=lead_id,
            comment_text=f"Interim Info email sent to {lead['email']} by {current_user.get('name', 'Agent')}",
            added_by=current_user.get("email", "agent")
        )

    return {
        "success": result.get("success", False),
        "message": "Interim Info email sent successfully" if result.get("success") else (result.get("error") or "Failed to send email"),
        "email_type": "INTERIM_INFO"
    }


# ============================================================================
# API ENDPOINTS - COMMUNICATIONS (Admin Only)
# Visibility & control over every email the portal sends.
# NOTE: /settings and /playbook routes MUST be registered before the
# /{lead_id} catch-all below, or FastAPI would treat them as lead ids.
# ============================================================================

class CCUpdateRequest(BaseModel):
    cc: List[str]


@app.get("/api/admin/communications")
async def list_communications(
    email_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """
    Communications log grouped by lead — one row per lead with counts,
    types sent and last activity. Click-through detail comes from
    GET /api/admin/communications/{lead_id}.
    """
    ensure_admin(current_user)

    match = {}
    if email_type:
        match["email_type"] = email_type.upper()
    if status:
        match["status"] = status.lower()
    if date_from or date_to:
        rng = {}
        try:
            if date_from:
                rng["$gte"] = datetime.fromisoformat(date_from)
            if date_to:
                # A bare date means "through the end of that day"
                rng["$lte"] = datetime.fromisoformat(date_to + "T23:59:59" if len(date_to) == 10 else date_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")
        match["sent_at"] = rng
    if search:
        match["$or"] = [
            {"lead_id": {"$regex": search, "$options": "i"}},
            {"lead_name": {"$regex": search, "$options": "i"}},
            {"to": {"$regex": search, "$options": "i"}},
        ]

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$lead_id",
            "lead_name": {"$first": "$lead_name"},
            "to": {"$first": "$to"},
            "email_count": {"$sum": 1},
            "failed_count": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "last_sent_at": {"$max": "$sent_at"},
            "types_sent": {"$addToSet": "$email_type"},
        }},
        {"$sort": {"last_sent_at": -1}},
    ]
    rows = await MongoDB.db.communications.aggregate(pipeline).to_list(length=None)
    total = len(rows)
    page_rows = rows[(page - 1) * limit: (page - 1) * limit + limit]
    for r in page_rows:
        r["lead_id"] = r.pop("_id")
    return {"total": total, "page": page, "limit": limit, "leads": page_rows}


@app.get("/api/admin/communications/settings")
async def get_communications_settings(current_user: dict = Depends(get_current_user)):
    """From (read-only, env-managed) + the 5 admin-editable CC lists."""
    ensure_admin(current_user)
    doc = await MongoDB.db.settings.find_one({"_id": comms.SETTINGS_DOC_ID}) or {}
    return {
        "from_email": comms.FROM_EMAIL,
        "from_name": comms.FROM_NAME,
        "from_editable": False,  # changing From would break the SendGrid verified sender
        "cc_lists": {t: doc.get("cc_lists", {}).get(t, []) for t in comms.EMAIL_TYPES},
        "cc_meta": doc.get("cc_meta", {}),
    }


@app.put("/api/admin/communications/settings/cc/{email_type}")
async def update_communications_cc(
    email_type: str,
    request: CCUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Replace one email type's CC list. Takes effect on the very next send."""
    ensure_admin(current_user)
    try:
        cleaned = await comms.set_cc_list(email_type.upper(), request.cc, current_user.get("email", "admin"))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return {"email_type": email_type.upper(), "cc": cleaned, "message": "CC list updated"}


@app.get("/api/admin/communications/playbook")
async def get_communications_playbook(current_user: dict = Depends(get_current_user)):
    """
    The email rulebook: for each email type — what triggers it, its
    conditions, rate limits, subject, From, and the live CC list.
    """
    ensure_admin(current_user)
    doc = await MongoDB.db.settings.find_one({"_id": comms.SETTINGS_DOC_ID}) or {}
    return {
        "from_email": comms.FROM_EMAIL,
        "from_name": comms.FROM_NAME,
        "playbook": comms.playbook_public(doc.get("cc_lists", {}), doc.get("cc_meta", {})),
    }


@app.get("/api/admin/communications/playbook/{email_type}/preview")
async def preview_communication_template(email_type: str, current_user: dict = Depends(get_current_user)):
    """Render the real email template with sample data (preview == reality)."""
    ensure_admin(current_user)
    try:
        return comms.render_preview(email_type.upper())
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))


@app.get("/api/admin/communications/{lead_id}")
async def get_lead_communications(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Full email timeline for one lead (newest first)."""
    ensure_admin(current_user)
    rows = await MongoDB.db.communications.find(
        {"lead_id": lead_id}, {"_id": 0}
    ).sort("sent_at", -1).to_list(length=200)
    return {"lead_id": lead_id, "total": len(rows), "communications": rows}


# ============================================================================
# API ENDPOINTS - GYM & PARTNER MANAGEMENT (Admin Only)
# ============================================================================

@app.post("/api/admin/gyms")
async def create_gym_endpoint(
    request: GymCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new gym (admin only)
    Body: GymCreateRequest model
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    try:
        # Debug: Log custom_plans
        print(f"[DEBUG] Creating gym '{request.gym_name}' with custom_plans: {request.custom_plans}")

        # Create gym using gym_db manager
        gym_id = await gym_db.create_gym(
            gym_name=request.gym_name,
            partner_name=request.partner_name,
            address=request.address,
            city=request.city,
            state=request.state,
            pincode=request.pincode,
            latitude=request.latitude,
            longitude=request.longitude,
            amenities=request.amenities,
            subscription_amount=request.subscription_amount,
            icon=request.icon,
            custom_plans=request.custom_plans
        )

        return {
            "message": "Gym created successfully",
            "gym_id": gym_id,
            "gym_name": request.gym_name,
            "partner_name": request.partner_name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating gym: {str(e)}")


@app.post("/api/admin/gyms/upload")
async def upload_gyms_csv_endpoint(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload gyms from CSV file (admin only)
    NEW CSV Format: Sr. No,Gym_Name,Provider,Center_Code,Center_type,Address,City,State,Latitude,Longitude,Pincode,Plan name,MRP,Discount,Price,Amenities
    Note: Multiple rows per Center_Code will be grouped into one gym with multiple plans
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    try:
        # Read CSV file. Use utf-8-sig so a leading BOM (Excel "Save As CSV"
        # adds one) is stripped from the first header name.
        content = await file.read()
        decoded_content = content.decode('utf-8-sig').splitlines()

        csv_reader = csv.DictReader(decoded_content)

        # Tolerant numeric parser: handles values Excel emits like "25.00%",
        # "7,900", "₹5925", or blank — strips %/commas/currency/whitespace.
        def to_number(val):
            s = str(val if val is not None else '').strip()
            s = s.replace('%', '').replace(',', '').replace('₹', '').replace('Rs', '').replace('rs', '').strip()
            return float(s) if s else 0.0

        # Discount must be stored as a FRACTION (0.40), because the frontend
        # renders it as `discount * 100`% (e.g. 0.40 -> "40% OFF").
        #   "40.00%" -> 0.40 ;  bare "40" -> 0.40 ;  already-fraction "0.4" -> 0.4
        def parse_discount(val):
            s = str(val if val is not None else '').strip()
            had_pct = '%' in s
            n = to_number(s)
            if had_pct:
                return n / 100.0
            return n / 100.0 if n > 1 else n

        # Group rows by Center_Code
        gyms_by_center = {}

        for i, row in enumerate(csv_reader, start=2):
            try:
                center_code = row.get('Center_Code', '').strip()
                if not center_code:
                    continue

                # Parse amenities. They may be separated by newlines AND/OR '•'
                # bullets. When the CSV is exported from Excel, in-cell newlines
                # can be lost during parsing, so '•' is the reliable separator —
                # normalize both to newlines, then split.
                amenities_str = row.get('Amenities', '')
                if amenities_str:
                    normalized = amenities_str.replace('•', '\n')
                    amenities = [a.strip() for a in normalized.split('\n') if a.strip()]
                else:
                    amenities = []

                # Create plan object. Discount may be "25.00%" → stored as fraction.
                # Each plan keeps ITS OWN amenities (they differ per tier, e.g.
                # Elite vs Pro), so the UI can show amenities for the selected plan.
                plan = {
                    'plan_name': row.get('Plan name', '').strip(),
                    'mrp': int(to_number(row.get('MRP', 0)) + 0.5),       # whole rupees, no decimals
                    'discount': parse_discount(row.get('Discount', 0)),
                    'price': int(to_number(row.get('Price', 0)) + 0.5),   # whole rupees, no decimals
                    'amenities': amenities
                }

                # Group by center code
                if center_code not in gyms_by_center:
                    gyms_by_center[center_code] = {
                        'gym_name': row.get('Gym_Name', '').strip(),
                        'provider': row.get('Provider', 'Cult').strip(),
                        'center_code': center_code,
                        'center_type': row.get('Center_type', '').strip(),
                        'address': row.get('Address', '').strip(),
                        'city': row.get('City', '').strip(),
                        'state': row.get('State', '').strip(),
                        'latitude': to_number(row.get('Latitude', 0)),
                        'longitude': to_number(row.get('Longitude', 0)),
                        'pincode': row.get('Pincode', '').strip(),
                        'amenities': amenities,
                        'plans': []
                    }

                # Add plan to this gym
                gyms_by_center[center_code]['plans'].append(plan)

            except Exception as e:
                print(f"[WARNING] Line {i} skipped: {str(e)}")
                continue

        # Now upsert gyms in database (update existing by center_code, else create).
        # This makes re-uploading a price/discount-updated sheet safe — it refreshes
        # existing gyms in place instead of creating duplicates.
        gyms_created = 0
        gyms_updated = 0
        errors = []

        for center_code, gym_data in gyms_by_center.items():
            try:
                result = await gym_db.upsert_gym_by_center_code(
                    gym_name=gym_data['gym_name'],
                    partner_name=gym_data['provider'],
                    address=gym_data['address'],
                    city=gym_data['city'],
                    state=gym_data['state'],
                    pincode=gym_data['pincode'],
                    latitude=gym_data['latitude'],
                    longitude=gym_data['longitude'],
                    amenities=gym_data['amenities'],
                    subscription_amount=int(min([p['price'] for p in gym_data['plans']])),  # Cheapest plan
                    center_code=center_code,
                    center_type=gym_data['center_type'],
                    plans=gym_data['plans']
                )

                if result.get("action") == "updated":
                    gyms_updated += 1
                else:
                    gyms_created += 1

            except Exception as e:
                errors.append(f"Center {center_code}: {str(e)}")

        return {
            "message": f"Processed {len(gyms_by_center)} centers: {gyms_created} created, {gyms_updated} updated",
            "gyms_created": gyms_created,
            "gyms_updated": gyms_updated,
            "total_centers": len(gyms_by_center),
            "errors": errors if errors else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")


@app.delete("/api/admin/gyms/{gym_id}")
async def delete_gym_endpoint(
    gym_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a gym (admin only)
    Note: Soft delete - gym is marked as inactive
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    success = await gym_db.delete_gym(gym_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Gym {gym_id} not found")

    return {
        "message": "Gym deleted successfully",
        "gym_id": gym_id
    }


@app.post("/api/admin/partners")
async def create_partner_endpoint(
    request: PartnerCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new partner (admin only)
    Body: PartnerCreateRequest model
    Note: Partners are derived from gyms. This creates a placeholder.
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    success = await gym_db.create_partner_entry(
        partner_name=request.name,
        description=request.description,
        icon=request.icon
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Partner '{request.name}' already exists"
        )

    return {
        "message": "Partner created successfully",
        "partner_name": request.name,
        "note": "Add gyms to this partner to activate it"
    }


@app.delete("/api/admin/partners/{partner_name}")
async def delete_partner_endpoint(
    partner_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a partner and all its gyms (admin only)
    Note: Soft delete - all gyms are marked as inactive
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    gyms_deleted = await gym_db.delete_partner(partner_name)

    if gyms_deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Partner '{partner_name}' not found or has no gyms"
        )

    return {
        "message": "Partner deleted successfully",
        "partner_name": partner_name,
        "gyms_deleted": gyms_deleted
    }


@app.get("/api/admin/reports/leads.csv")
async def export_leads_csv(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None)
):
    """
    Export leads to CSV with optional filters
    Requires JWT authentication
    """
    # Same IST-day semantics as the leads table, so export rows match it
    date_from, date_to = parse_ist_date_range(from_date, to_date)

    # Get all leads (no pagination for export)
    result = await lead_manager.get_all_leads(
        skip=0,
        limit=10000,  # Max 10k records for CSV
        status_filter=status,
        payment_status_filter=payment_status,
        city_filter=city,
        assigned_to_filter=assigned_to,
        date_from=date_from,
        date_to=date_to
    )

    leads = result.get('leads', [])

    # CSV INJECTION DEFENSE — sanitize any cell that starts with =, +, -, @, tab, CR.
    # Excel/Google Sheets treat these as formulas; prefix with single quote to neutralize.
    # OWASP CSV Injection mitigation:
    #   https://owasp.org/www-community/attacks/CSV_Injection
    _DANGEROUS_CSV_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
    def csv_safe(value):
        if value is None:
            return ''
        s = str(value)
        if s and s[0] in _DANGEROUS_CSV_PREFIXES:
            return "'" + s
        return s

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Admins get the full export including audit history; agents get a reduced
    # export with NO audit/history/comments columns (agents can't view audit logs).
    include_audit = is_admin(current_user)

    base_headers = [
        "Lead ID",
        "Created At",
        "Status",
        "Full Name",
        "Email",
        "Phone",
        "City",
        "State",
        "Gym Name",
        "Partner",
        "Preferred Plan",
        "Payment Status",
        "Payment Amount",
        "Reference ID",
        "Recon ID",
        "Invoice Number",
        "Billing Address",
        "Message",
        "Gym ID",
        "Assigned To",
        "Assigned To Name",
        "Assigned At",
        "User Latitude",
        "User Longitude",
        "Payment Updated At",
        "Lead Updated At",
    ]
    audit_headers = [
        "Comments Count",
        "Total Audit Entries",
        "Latest Status Update",
        "Latest Payment Update",
        "Latest Plan Change",
        "Plan Changed",
        "All Comments",
    ]

    # Write header
    writer.writerow(base_headers + (audit_headers if include_audit else []))

    # Write data rows
    for lead in leads:
        created_at = lead.get('created_at', '')
        if isinstance(created_at, datetime):
            created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')

        user_location = lead.get('user_location', {})
        payment = lead.get('payment', {})
        comments = lead.get('comments', [])
        audit_log = lead.get('audit_log', [])

        # Format additional timestamp fields
        assigned_at = lead.get('assigned_at', '')
        if isinstance(assigned_at, datetime):
            assigned_at = assigned_at.strftime('%Y-%m-%d %H:%M:%S')
        payment_updated_at = payment.get('updated_at', '')
        if isinstance(payment_updated_at, datetime):
            payment_updated_at = payment_updated_at.strftime('%Y-%m-%d %H:%M:%S')
        lead_updated_at = lead.get('updated_at', '')
        if isinstance(lead_updated_at, datetime):
            lead_updated_at = lead_updated_at.strftime('%Y-%m-%d %H:%M:%S')

        # Extract latest audit entries
        latest_status_update = ""
        latest_payment_update = ""
        latest_plan_change = ""
        plan_changed_to = ""  # NEW: just the new plan name from latest plan_change (or empty if never changed)

        # Process audit log (most recent first)
        for entry in reversed(audit_log):
            action = entry.get('action', '')
            timestamp = entry.get('timestamp', '')
            user = entry.get('user', '')

            if isinstance(timestamp, datetime):
                timestamp = timestamp.strftime('%Y-%m-%d %H:%M')

            if action == 'status_change' and not latest_status_update:
                old_val = entry.get('old_value', '')
                new_val = entry.get('new_value', '')
                reason = entry.get('reason', '')
                latest_status_update = f"{timestamp} | {user} | {old_val} → {new_val}"
                if reason:
                    latest_status_update += f" | Reason: {reason}"

            elif action == 'payment_update' and not latest_payment_update:
                old_val = entry.get('old_value', '')
                new_val = entry.get('new_value', '')
                details = entry.get('details', {})
                latest_payment_update = f"{timestamp} | {user} | {old_val} → {new_val}"
                if details:
                    if 'amount' in details:
                        latest_payment_update += f" | Amount: ₹{details['amount']}"
                    if 'payment_link' in details:
                        latest_payment_update += f" | Link: {details['payment_link']}"

            elif action == 'plan_change' and not latest_plan_change:
                old_val = entry.get('old_value', '')
                new_val = entry.get('new_value', '')
                reason = entry.get('reason', '')
                latest_plan_change = f"{timestamp} | {user} | {old_val} → {new_val}"
                if reason:
                    latest_plan_change += f" | Reason: {reason}"
                plan_changed_to = new_val  # full plan name e.g. "Cultpass Elite || 12 Months"

        # Format all comments
        all_comments = ""
        for comment in comments:
            comment_time = comment.get('timestamp', '')
            if isinstance(comment_time, datetime):
                comment_time = comment_time.strftime('%Y-%m-%d %H:%M')
            comment_user = comment.get('added_by', '')
            comment_text = comment.get('comment', '')
            all_comments += f"[{comment_time} - {comment_user}] {comment_text}; "

        base_row = [
            csv_safe(lead.get('lead_id', '')),
            csv_safe(created_at),
            csv_safe(lead.get('status', '')),
            csv_safe(lead.get('full_name', '')),
            csv_safe(lead.get('email', '')),
            csv_safe(lead.get('phone', '')),
            csv_safe(user_location.get('city', '')),
            csv_safe(user_location.get('state', '')),
            csv_safe(lead.get('gym_name', '')),
            csv_safe(lead.get('partner_name', '')),
            csv_safe(lead.get('preferred_plan', '')),
            csv_safe(payment.get('status', '')),
            csv_safe(payment.get('amount', '')),
            csv_safe(payment.get('payment_link', '')),    # Reference ID (Razorpay txn ID, stored in legacy field name)
            csv_safe(payment.get('recon_id', '')),         # Recon ID (HHGYM-XXXXX)
            csv_safe(payment.get('invoice_number', '')),   # Invoice Number (manually entered)
            csv_safe(lead.get('billing_address', '')),
            csv_safe(lead.get('message', '')),
            csv_safe(lead.get('gym_id', '')),
            csv_safe(lead.get('assigned_to', '')),
            csv_safe(lead.get('assigned_to_name', '')),
            csv_safe(assigned_at),
            csv_safe(user_location.get('latitude', '')),
            csv_safe(user_location.get('longitude', '')),
            csv_safe(payment_updated_at),
            csv_safe(lead_updated_at),
        ]
        if include_audit:
            base_row += [
                len(comments),
                len(audit_log),
                csv_safe(latest_status_update),
                csv_safe(latest_payment_update),
                csv_safe(latest_plan_change),
                csv_safe(plan_changed_to),
                csv_safe(all_comments.strip())
            ]
        writer.writerow(base_row)

    # Get CSV content
    csv_content = output.getvalue()
    output.close()

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"gym_habit_leads_{timestamp}.csv"

    # Return as streaming response
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# ============================================================================
# API ENDPOINTS - USER MANAGEMENT (Admin Only)
# ============================================================================

@app.get("/api/admin/users")
async def get_all_users(current_user: dict = Depends(get_current_user)):
    """
    Get all users (admin only)
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    # Fetch all users
    users = await MongoDB.db.users.find({}).to_list(None)

    # Remove sensitive data
    safe_users = []
    for user in users:
        safe_users.append({
            "user_id": str(user['_id']),
            "email": user['email'],
            "name": user['name'],
            "role": user['role'],
            "phone": user.get('phone', ''),
            "is_active": user.get('is_active', True),
            "created_at": user.get('created_at'),
            "last_login": user.get('last_login'),
            "login_count": user.get('login_count', 0)
        })

    return {"users": safe_users, "total": len(safe_users)}



@app.put("/api/admin/gyms/{gym_id}")
async def update_gym_endpoint(
    gym_id: int,
    request: GymCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Update an existing gym (admin only)
    """
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    try:
        success = await gym_db.update_gym(
            gym_id=gym_id,
            gym_name=request.gym_name,
            partner_name=request.partner_name,
            address=request.address,
            city=request.city,
            state=request.state,
            pincode=request.pincode,
            latitude=request.latitude,
            longitude=request.longitude,
            amenities=request.amenities,
            subscription_amount=request.subscription_amount,
            icon=request.icon,
            custom_plans=request.custom_plans
        )

        if not success:
            raise HTTPException(status_code=404, detail="Gym not found")

        return {"success": True, "message": "Gym updated successfully"}
    except HTTPException:
        raise  # Re-raise HTTPException as-is
    except Exception as e:
        print(f"Error updating gym: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/partners/{partner_name}")
async def update_partner_endpoint(
    partner_name: str,
    request: PartnerCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Update an existing partner (admin only)
    """
    print(f"\n=== UPDATE PARTNER ENDPOINT ===")
    print(f"Partner Name (from URL): {partner_name}")
    print(f"New Name: {request.name}")
    print(f"Description: {request.description}")
    print(f"Has Icon: {request.icon is not None}")
    if request.icon:
        print(f"Icon length: {len(request.icon)}")
    print(f"User: {current_user.get('email')}")

    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    try:
        success = await gym_db.update_partner(
            old_name=partner_name,
            new_name=request.name,
            description=request.description,
            icon=request.icon
        )

        print(f"Update result: {success}")

        if not success:
            print(f"[ERROR] Partner update failed - partner not found: {partner_name}")
            raise HTTPException(status_code=404, detail=f"Partner '{partner_name}' not found")

        print(f"[SUCCESS] Partner updated: {partner_name} -> {request.name}")
        return {"success": True, "message": "Partner updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Partner update exception: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/users")
async def create_user(
    email: EmailStr = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    phone: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new user (admin only)
    Valid roles: admin, agent. `phone` is an optional contact field (not used for login).
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    # Validate role
    valid_roles = ["admin", "agent"]
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )

    # Validate password
    if len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long"
        )

    # Check if user already exists
    existing_user = await MongoDB.db.users.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400, detail=f"User with email {email} already exists")

    # Hash password
    from auth import hash_password
    password_hash = hash_password(password)

    # Create user document
    new_user = {
        "email": email,
        "name": name,
        "password_hash": password_hash,
        "role": role,
        "phone": (phone or "").strip(),
        "is_active": True,
        "created_at": datetime.utcnow(),
        "created_by": current_user['email'],
        "login_count": 0
    }

    # Insert user
    result = await MongoDB.db.users.insert_one(new_user)

    return {
        "message": "User created successfully",
        "user": {
            "user_id": str(result.inserted_id),
            "email": email,
            "name": name,
            "role": role
        }
    }


@app.patch("/api/admin/users/{user_id}")
async def update_user(
    user_id: str,
    role: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Update user role or active status (admin only)
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    # Validate role if provided
    if role is not None:
        valid_roles = ["admin", "agent"]
        if role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
            )

    # Build update document
    from bson import ObjectId
    update_data = {"updated_at": datetime.utcnow(), "updated_by": current_user['email']}

    if role is not None:
        update_data["role"] = role

    if is_active is not None:
        update_data["is_active"] = is_active

    # Update user
    try:
        result = await MongoDB.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid user ID: {str(e)}")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    return {"message": "User updated successfully", "user_id": user_id}


@app.delete("/api/admin/users/{user_id}")
async def deactivate_user(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Deactivate a user (admin only). Users are not deleted, just marked inactive.
    A deactivated AGENT's open leads (status != closed, payment != paid) are
    redistributed across the remaining active agents via round-robin (admin fallback).
    """
    # Check if user is admin
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    from bson import ObjectId
    try:
        target_user = await MongoDB.db.users.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid user ID: {str(e)}")

    if not target_user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    # Only agents can be deactivated; admins are protected
    if target_user.get('role') == 'admin':
        raise HTTPException(status_code=403, detail="Cannot deactivate admin users")

    # Deactivate FIRST so this agent is excluded from the redistribution rotation
    await MongoDB.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "is_active": False,
                "deactivated_at": datetime.utcnow(),
                "deactivated_by": current_user['email']
            }
        }
    )

    # Redistribute this agent's open leads to the remaining active agents
    reassignment = await lead_manager.reassign_open_leads_from_agent(
        target_user['email'], current_user['email']
    )

    return {
        "message": "User deactivated successfully",
        "user_id": user_id,
        "leads_reassigned": reassignment["reassigned"]
    }


@app.post("/api/admin/users/{user_id}/activate")
async def activate_user(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Re-activate a previously deactivated user (admin only).
    A reactivated agent automatically rejoins the round-robin rotation
    (rotation is just a live query for role==agent & is_active==true).
    """
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Access forbidden. Admin only.")

    from bson import ObjectId
    try:
        result = await MongoDB.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "is_active": True,
                    "reactivated_at": datetime.utcnow(),
                    "reactivated_by": current_user['email']
                }
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid user ID: {str(e)}")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    return {"message": "User activated successfully", "user_id": user_id}


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """
    Health check. Reports the database it is configured to reach and whether
    that connection works, so a misconfigured deployment is diagnosable without
    server logs. Credentials are never included.
    """
    # Host only — never the username or password
    target = config.MONGODB_URL
    if "@" in target:
        target = target.rsplit("@", 1)[1]
    target = target.split("/")[0].split("?")[0]

    info = {
        "status": "unhealthy",
        "database": "mongodb",
        "configured_host": target,
        "configured_db": config.MONGODB_DB_NAME,
    }

    if MongoDB.db is None:
        info["error"] = "No database connection was established at startup."
        info["hint"] = "Set MONGODB_URL and MONGODB_DB_NAME, then redeploy."
        return info

    try:
        total_gyms = await MongoDB.db.gyms.count_documents({"is_active": True})
        partners = await gym_db.get_all_partners()
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return info

    info.update({"status": "healthy", "gyms_loaded": total_gyms, "partners": len(partners)})
    return info


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("GYM HABIT - Demo Webapp Partner Gym Finder (MongoDB)")
    print("=" * 60)
    print("[INFO] Starting server...")
    print("[INFO] Main page: http://localhost:8000")
    print("[INFO] Admin panel: http://localhost:8000/admin")
    print("[INFO] API docs: http://localhost:8000/docs")
    print("=" * 60)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

