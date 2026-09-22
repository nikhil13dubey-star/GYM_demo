# Gym Habit - Complete API Documentation

**Version:** 2.0.0
**Last Updated:** 2025-12-14
**Tech Stack:** FastAPI + MongoDB + JWT Authentication

---

## 📑 Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Public APIs](#public-apis)
4. [Auth APIs](#auth-apis)
5. [Admin Lead Management APIs](#admin-lead-management-apis)
6. [Admin Reporting APIs](#admin-reporting-apis)
7. [Admin User Management APIs](#admin-user-management-apis)
8. [Data Models](#data-models)
9. [Error Handling](#error-handling)
10. [Testing Guide](#testing-guide)

---

## Overview

### Total API Endpoints: 24

| Category | Count | Authentication Required |
|----------|-------|------------------------|
| Public APIs | 6 | No |
| Auth APIs | 4 | Partial (login: no, others: yes) |
| Admin Lead Management | 9 | Yes (JWT) |
| Admin Reporting | 1 | Yes (JWT) |
| Admin User Management | 4 | Yes (JWT, Admin only) |

### Base URL
- **Development:** `http://localhost:8000`
- **Production:** `https://your-domain.vercel.app`

---

## Authentication

All protected endpoints require JWT Bearer token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### User Roles
- **admin** - Full access to all endpoints
- **agent** - Can manage leads, view reports
- **viewer** - Read-only access to leads

---

## Public APIs

### 1. Get All Partners
```http
GET /api/partners
```

**Response:**
```json
{
  "partners": [
    {"name": "Cult", "count": 6},
    {"name": "Gold's Gym", "count": 6},
    {"name": "Anytime Fitness", "count": 6},
    {"name": "Fitness First", "count": 6},
    {"name": "Talwalkar's", "count": 6}
  ],
  "total": 5
}
```

---

### 2. Get All Gyms (with optional filter)
```http
GET /api/gyms?partner={partner_name}
```

**Query Parameters:**
- `partner` (optional) - Filter by partner name

**Response:**
```json
{
  "gyms": [
    {
      "gym_id": 1,
      "name": "Cult Koramangala",
      "partner_name": "Cult",
      "address": "123 Main St, Koramangala, Bangalore",
      "city": "Bangalore",
      "state": "Karnataka",
      "pincode": "560034",
      "base_monthly": 2500,
      "amenities": "Cardio,Weights,Yoga,Showers",
      "is_active": true
    }
  ],
  "total": 30,
  "filtered_by": "Cult"
}
```

---

### 3. Get Nearby Gyms (by coordinates)
```http
GET /api/gyms/nearby?lat={latitude}&lon={longitude}&limit={limit}&max_distance={km}
```

**Query Parameters:**
- `lat` (required) - Latitude (e.g., 12.9716)
- `lon` (required) - Longitude (e.g., 77.5946)
- `limit` (optional) - Max results (default: 10)
- `max_distance` (optional) - Max distance in km (default: 50)

**Response:**
```json
{
  "gyms": [
    {
      "gym_id": 1,
      "name": "Cult Koramangala",
      "distance": 2.5,
      "...": "other gym fields"
    }
  ],
  "user_location": {"latitude": 12.9716, "longitude": 77.5946},
  "total": 5,
  "max_distance_km": 50
}
```

---

### 4. Search Gyms by Location (city/area)
```http
GET /api/gyms/search-by-location?location={city_or_area}&limit={limit}
```

**Query Parameters:**
- `location` (required) - City or area name (e.g., "Andheri Mumbai")
- `limit` (optional) - Max results (default: 10)

**Uses Google Geocoding API** to convert location to coordinates.

---

### 5. Get Gym Details
```http
GET /api/gyms/{gym_id}
```

**Response:**
```json
{
  "gym_id": 1,
  "name": "Cult Koramangala",
  "partner_name": "Cult",
  "address": "123 Main St, Koramangala, Bangalore",
  "city": "Bangalore",
  "state": "Karnataka",
  "pincode": "560034",
  "base_monthly": 2500,
  "amenities": "Cardio,Weights,Yoga,Showers",
  "subscription_plans": {
    "1 Month": {
      "duration": "1 Month",
      "total_amount": 2500,
      "monthly_amount": 2500,
      "discount_percent": 0,
      "savings": 0
    },
    "3 Months": {
      "duration": "3 Months",
      "total_amount": 7125,
      "monthly_amount": 2375,
      "discount_percent": 5,
      "savings": 375
    }
  }
}
```

---

### 6. Submit Subscription Request
```http
POST /api/subscription/request
```

**Body (Form Data):**
```
full_name: string (required, max 100 chars)
email: EmailStr (optional)
phone: string (required, 10 digits)
gym_id: int (required)
preferred_plan: string (required, e.g., "1 Month", "3 Months")
billing_address: string (optional)
message: string (optional)
user_latitude: float (optional)
user_longitude: float (optional)
user_city: string (optional)
```

**Response:**
```json
{
  "message": "Subscription request submitted successfully!",
  "lead_id": "GYM_20251214_0001",
  "gym_name": "Cult Koramangala",
  "partner_name": "Cult"
}
```

---

## Auth APIs

### 1. Login
```http
POST /api/auth/login
```

**Body (JSON):**
```json
{
  "email": "admin@example.com",
  "password": "Demo@12345"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR...",
  "token_type": "bearer",
  "user": {
    "email": "admin@example.com",
    "name": "Admin User",
    "role": "admin"
  }
}
```

---

### 2. Get Current User
```http
GET /api/auth/me
```

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "email": "admin@example.com",
  "name": "Admin User",
  "role": "admin",
  "is_active": true,
  "created_at": "2025-12-01T10:00:00Z",
  "last_login": "2025-12-14T14:30:00Z",
  "login_count": 15
}
```

---

### 3. Change Password
```http
POST /api/auth/change-password
```

**Headers:**
```
Authorization: Bearer <token>
```

**Body (Form Data):**
```
old_password: string (required)
new_password: string (required, min 8 chars)
```

**Response:**
```json
{
  "message": "Password changed successfully"
}
```

---

### 4. Logout
```http
POST /api/auth/logout
```

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "Logged out successfully"
}
```

---

## Admin Lead Management APIs

### 1. Get All Leads (with filters & pagination)
```http
GET /api/admin/leads?page={page}&per_page={per_page}&status={status}&payment_status={payment_status}&city={city}
```

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `page` (optional) - Page number (default: 1)
- `per_page` (optional) - Results per page (default: 20, max: 100)
- `status` (optional) - Filter by status: new, contacted, interested, not_interested, closed
- `payment_status` (optional) - Filter by payment: pending, link_shared, paid, failed
- `city` (optional) - Filter by city name

**Response:**
```json
{
  "leads": [
    {
      "lead_id": "GYM_20251214_0001",
      "created_at": "2025-12-14T10:00:00Z",
      "status": "new",
      "full_name": "John Doe",
      "email": "john@example.com",
      "phone": "9876543210",
      "gym_name": "Cult Koramangala",
      "partner_name": "Cult",
      "preferred_plan": "3 Months",
      "payment": {
        "status": "pending",
        "amount": null,
        "payment_link": null
      },
      "comments": [],
      "user_location": {
        "city": "Bangalore"
      }
    }
  ],
  "total": 150,
  "page": 1,
  "pages": 8,
  "per_page": 20
}
```

---

### 2. Get Single Lead Details
```http
GET /api/admin/leads/{lead_id}
```

**Headers:**
```
Authorization: Bearer <token>
```

**Response:** Same structure as individual lead in the list above

---

### 3. Update Lead Status
```http
PATCH /api/admin/leads/{lead_id}/status
```

**Headers:**
```
Authorization: Bearer <token>
```

**Body (Form Data):**
```
status: string (required) - new, contacted, interested, not_interested, closed
reason: string (optional) - Reason for status change
```

**Response:**
```json
{
  "message": "Status updated successfully",
  "lead_id": "GYM_20251214_0001",
  "new_status": "contacted"
}
```

---

### 4. Add Comment to Lead
```http
POST /api/admin/leads/{lead_id}/comments
```

**Headers:**
```
Authorization: Bearer <token>
```

**Body (Form Data):**
```
comment: string (required) - Comment text
```

**Response:**
```json
{
  "message": "Comment added successfully",
  "lead_id": "GYM_20251214_0001"
}
```

---

### 5. Update Payment Information
```http
PATCH /api/admin/leads/{lead_id}/payment
```

**Headers:**
```
Authorization: Bearer <token>
```

**Body (Form Data):**
```
payment_status: string (required) - pending, link_shared, paid, failed
payment_link: string (optional) - Payment link URL
amount: int (optional) - Payment amount in rupees
```

**Response:**
```json
{
  "message": "Payment updated successfully",
  "lead_id": "GYM_20251214_0001",
  "payment_status": "paid"
}
```

---

### 6. Update Membership Plan
```http
PATCH /api/admin/leads/{lead_id}/plan
```

**Headers:**
```
Authorization: Bearer <token>
```

**Body (Form Data):**
```
new_plan: string (required) - 1 Month, 3 Months, 6 Months, 12 Months
reason: string (optional) - Reason for plan change
```

**Response:**
```json
{
  "message": "Plan updated successfully",
  "lead_id": "GYM_20251214_0001",
  "new_plan": "6 Months"
}
```

---

### 7. Get Audit Trail
```http
GET /api/admin/leads/{lead_id}/audit
```

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "lead_id": "GYM_20251214_0001",
  "audit_trail": [
    {
      "timestamp": "2025-12-14T10:00:00Z",
      "action": "status_change",
      "user": "admin@example.com",
      "old_value": "new",
      "new_value": "contacted",
      "reason": "Called the customer"
    },
    {
      "timestamp": "2025-12-14T10:30:00Z",
      "action": "comment_added",
      "user": "admin@example.com",
      "comment": "User is very interested"
    }
  ]
}
```

---

### 8. Get Dashboard Stats
```http
GET /api/admin/stats
```

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "total_leads": 150,
  "total_gyms": 30,
  "status_breakdown": {
    "new": 50,
    "contacted": 40,
    "interested": 30,
    "not_interested": 20,
    "closed": 10
  },
  "payment_breakdown": {
    "pending": 100,
    "link_shared": 30,
    "paid": 15,
    "failed": 5
  }
}
```

---

## Admin Reporting APIs

### Export Leads to CSV
```http
GET /api/admin/reports/leads.csv?status={status}&payment_status={payment_status}&city={city}&from_date={YYYY-MM-DD}&to_date={YYYY-MM-DD}
```

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters (all optional):**
- `status` - Filter by status
- `payment_status` - Filter by payment status
- `city` - Filter by city
- `from_date` - Start date (YYYY-MM-DD format)
- `to_date` - End date (YYYY-MM-DD format)

**Response:** CSV file download
**Filename:** `gym_habit_leads_YYYYMMDD_HHMMSS.csv`
**Max Records:** 10,000

**CSV Columns:**
```
Lead ID, Created At, Status, Full Name, Email, Phone, City,
Gym Name, Partner, Preferred Plan, Payment Status, Payment Amount,
Payment Link, Billing Address, Message, Comments Count
```

---

## Admin User Management APIs

### 1. Get All Users
```http
GET /api/admin/users
```

**Headers:**
```
Authorization: Bearer <token>
```

**Required Role:** admin

**Response:**
```json
{
  "users": [
    {
      "user_id": "507f1f77bcf86cd799439011",
      "email": "admin@example.com",
      "name": "Admin User",
      "role": "admin",
      "is_active": true,
      "created_at": "2025-12-01T00:00:00Z",
      "last_login": "2025-12-14T14:30:00Z",
      "login_count": 15
    }
  ],
  "total": 1
}
```

---

### 2. Create New User
```http
POST /api/admin/users
```

**Headers:**
```
Authorization: Bearer <token>
```

**Required Role:** admin

**Body (Form Data):**
```
email: EmailStr (required)
name: string (required)
password: string (required, min 8 chars)
role: string (required) - admin, agent, viewer
```

**Response:**
```json
{
  "message": "User created successfully",
  "user": {
    "user_id": "507f1f77bcf86cd799439012",
    "email": "agent@example.com",
    "name": "Agent User",
    "role": "agent"
  }
}
```

---

### 3. Update User
```http
PATCH /api/admin/users/{user_id}
```

**Headers:**
```
Authorization: Bearer <token>
```

**Required Role:** admin

**Body (Form Data):**
```
role: string (optional) - admin, agent, viewer
is_active: boolean (optional) - true/false
```

**Response:**
```json
{
  "message": "User updated successfully",
  "user_id": "507f1f77bcf86cd799439012"
}
```

---

### 4. Deactivate User
```http
DELETE /api/admin/users/{user_id}
```

**Headers:**
```
Authorization: Bearer <token>
```

**Required Role:** admin

**Note:** Users are not deleted, just marked as inactive

**Response:**
```json
{
  "message": "User deactivated successfully",
  "user_id": "507f1f77bcf86cd799439012"
}
```

---

## Data Models

### Lead Document
```json
{
  "lead_id": "GYM_20251214_0001",
  "created_at": "2025-12-14T10:00:00Z",
  "updated_at": "2025-12-14T10:30:00Z",
  "gym_id": 1,
  "gym_name": "Cult Koramangala",
  "partner_name": "Cult",
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone": "9876543210",
  "preferred_plan": "3 Months",
  "billing_address": "123 Main St",
  "message": "I want to join ASAP",
  "user_location": {
    "latitude": 12.9716,
    "longitude": 77.5946,
    "city": "Bangalore"
  },
  "status": "new",
  "payment": {
    "status": "pending",
    "amount": null,
    "payment_link": null,
    "updated_at": null
  },
  "comments": [
    {
      "timestamp": "2025-12-14T10:30:00Z",
      "user": "admin@example.com",
      "text": "User is interested"
    }
  ],
  "audit_log": [
    {
      "timestamp": "2025-12-14T10:00:00Z",
      "action": "status_change",
      "user": "admin@example.com",
      "old_value": "new",
      "new_value": "contacted"
    }
  ]
}
```

### User Document
```json
{
  "_id": "507f1f77bcf86cd799439011",
  "email": "admin@example.com",
  "name": "Admin User",
  "password_hash": "$2b$12$...",
  "role": "admin",
  "is_active": true,
  "created_at": "2025-12-01T00:00:00Z",
  "created_by": "system",
  "last_login": "2025-12-14T14:30:00Z",
  "login_count": 15
}
```

---

## Error Handling

All endpoints return consistent error responses:

### 400 Bad Request
```json
{
  "detail": "Invalid status. Must be one of: new, contacted, interested, not_interested, closed"
}
```

### 401 Unauthorized
```json
{
  "detail": "Invalid authentication credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Access forbidden. Admin only."
}
```

### 404 Not Found
```json
{
  "detail": "Lead GYM_20251214_0001 not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## Testing Guide

### 1. Get JWT Token
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "Demo@12345"}'
```

### 2. Use Token in Requests
```bash
curl -X GET http://localhost:8000/api/admin/leads \
  -H "Authorization: Bearer <your_token_here>"
```

### 3. Test Lead Management
```bash
# Update status
curl -X PATCH http://localhost:8000/api/admin/leads/GYM_20251214_0001/status \
  -H "Authorization: Bearer <token>" \
  -F "status=contacted" \
  -F "reason=Called the customer"

# Add comment
curl -X POST http://localhost:8000/api/admin/leads/GYM_20251214_0001/comments \
  -H "Authorization: Bearer <token>" \
  -F "comment=User is very interested"

# Update payment
curl -X PATCH http://localhost:8000/api/admin/leads/GYM_20251214_0001/payment \
  -H "Authorization: Bearer <token>" \
  -F "payment_status=paid" \
  -F "amount=7125"
```

### 4. Test CSV Export
```bash
curl -X GET "http://localhost:8000/api/admin/reports/leads.csv?status=new" \
  -H "Authorization: Bearer <token>" \
  -o leads_export.csv
```

---

## Notes

1. **MongoDB Audit Logging:** All lead updates (status, payment, plan changes) are automatically logged with timestamp, user, and reason.

2. **Pagination:** Default page size is 20, maximum is 100 records per request.

3. **JWT Expiration:** Tokens expire after 24 hours (configurable in `config.py`).

4. **Role-Based Access:**
   - **Admin** - Full access to all endpoints
   - **Agent** - Can manage leads and view reports
   - **Viewer** - Read-only access to leads

5. **CSV Export Limit:** Maximum 10,000 records per export to prevent timeouts.

6. **Password Requirements:** Minimum 8 characters for all passwords.

---

**Last Updated:** 2025-12-14
**Generated by:** Claude Code
**Repository:** https://github.com/nikhil13dubey-star/GYM_demo
