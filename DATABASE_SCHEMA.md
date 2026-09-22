# Gym Habit - MongoDB Database Schema
**Complete Database Structure Documentation**

## Overview

**Database**: `gym_habit` (MongoDB)
**Collections**: 4 (gyms, leads, partners, users)
**Total Indexes**: 14
**Estimated Storage**: ~10MB per 1,000 gyms, ~5MB per 1,000 leads

---

## Collection 1: `gyms`

### Purpose
Stores all gym/partner location data with geospatial coordinates for proximity searches.

### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Yes | MongoDB auto-generated ID |
| `gym_id` | Integer | Yes | Auto-incremented unique ID (1, 2, 3...) |
| `gym_name` | String | Yes | Name of the gym (e.g., "Cult Andheri West") |
| `partner_name` | String | Yes | Partner brand (e.g., "Cult", "Gold's Gym") |
| `address` | String | Yes | Full street address |
| `city` | String | Yes | City name (e.g., "Mumbai") |
| `state` | String | Yes | State name (e.g., "Maharashtra") |
| `pincode` | String | Yes | 6-digit Indian pincode |
| `latitude` | Float | Yes | Latitude coordinate (-90 to 90) |
| `longitude` | Float | Yes | Longitude coordinate (-180 to 180) |
| `location` | GeoJSON Point | Yes | GeoJSON format for MongoDB geospatial queries |
| `amenities` | Array[String] | Yes | List of amenities (e.g., ["AC", "Parking"]) |
| `subscription_amount` | Integer | Yes | Base monthly subscription price (₹) |
| `custom_plans` | Object | No | Optional custom pricing for different durations |
| `icon` | String | No | Emoji or base64 encoded image |
| `is_active` | Boolean | Yes | Soft delete flag (true = active, false = deleted) |
| `created_at` | Date | Yes | Gym creation timestamp |
| `updated_at` | Date | No | Last update timestamp |
| `deleted_at` | Date | No | Soft delete timestamp |

### Sample Document

```javascript
{
  "_id": ObjectId("6584a1b2c3d4e5f6a7b8c9d0"),
  "gym_id": 1,
  "gym_name": "Cult Andheri West",
  "partner_name": "Cult",
  "address": "Plot 123, Veera Desai Road, Andheri West",
  "city": "Mumbai",
  "state": "Maharashtra",
  "pincode": "400053",
  "latitude": 19.1136,
  "longitude": 72.8697,
  "location": {
    "type": "Point",
    "coordinates": [72.8697, 19.1136]  // [longitude, latitude]
  },
  "amenities": [
    "Air Conditioning",
    "Parking",
    "Showers",
    "Lockers",
    "WiFi",
    "Personal Training"
  ],
  "subscription_amount": 1499,
  "custom_plans": {
    "1_month": 1499,
    "3_months": 4200,    // 7% discount
    "6_months": 7900,    // 12% discount
    "12_months": 14900   // 17% discount
  },
  "icon": "🏋️",
  "is_active": true,
  "created_at": ISODate("2024-01-01T00:00:00Z"),
  "updated_at": ISODate("2024-12-15T10:30:00Z")
}
```

### Indexes

```javascript
db.gyms.createIndex({ "location": "2dsphere" });           // For $near geospatial queries
db.gyms.createIndex({ "gym_id": 1 }, { unique: true });    // Unique gym ID
db.gyms.createIndex({ "pincode": 1 });                     // Fast pincode search
db.gyms.createIndex({ "city": 1 });                        // Fast city search
db.gyms.createIndex({ "is_active": 1 });                   // Filter active gyms
```

### Notes
- `location` must be in GeoJSON format for geospatial queries
- `gym_id` is auto-incremented (not MongoDB `_id`)
- `custom_plans` is optional; if not provided, plans are auto-calculated
- Soft delete: `is_active = false` instead of actual deletion

---

## Collection 2: `leads`

### Purpose
Stores user subscription requests/leads with full audit trail.

### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Yes | MongoDB auto-generated ID |
| `lead_id` | String | Yes | Human-readable ID (GYM_YYYYMMDD_XXXX) |
| `created_at` | Date | Yes | Lead creation timestamp |
| `updated_at` | Date | No | Last update timestamp |
| `gym_id` | Integer | Yes | Reference to gyms.gym_id |
| `gym_name` | String | Yes | Gym name (denormalized for performance) |
| `partner_name` | String | Yes | Partner name (denormalized) |
| `full_name` | String | Yes | User's full name |
| `email` | String | No | User's email (optional) |
| `phone` | String | Yes | 10-digit Indian mobile number |
| `billing_address` | String | No | User's billing address |
| `message` | String | No | Optional message from user |
| `user_location` | Object | No | Where user searched from |
| `status` | String | Yes | Lead status (enum) |
| `preferred_plan` | String | Yes | Selected subscription plan |
| `assigned_to` | String | No | Email of assigned admin/agent |
| `assigned_to_name` | String | No | Name of assigned user |
| `assigned_at` | Date | No | Assignment timestamp |
| `payment` | Object | Yes | Payment tracking object |
| `comments` | Array[Object] | Yes | Array of comments/notes |
| `audit_log` | Array[Object] | Yes | Full audit trail |

### Nested Objects

#### `user_location`
```javascript
{
  "latitude": 19.1136,
  "longitude": 72.8697,
  "city": "Mumbai"
}
```

#### `payment`
```javascript
{
  "status": "pending",         // pending | link_shared | paid | failed
  "amount": 4200,              // Amount in ₹
  "payment_link": "https://razorpay.me/abc123",
  "updated_at": ISODate("...")
}
```

#### `comments` (Array)
```javascript
[
  {
    "timestamp": ISODate("..."),
    "user": "admin@example.com",
    "text": "Called customer, interested in 3-month plan"
  }
]
```

#### `audit_log` (Array)
```javascript
[
  {
    "timestamp": ISODate("..."),
    "action": "status_change",     // status_change | payment_update | plan_change | comment_added
    "user": "admin@example.com",
    "old_value": "new",
    "new_value": "contacted",
    "reason": "First contact made"  // Optional
  }
]
```

### Sample Document

```javascript
{
  "_id": ObjectId("6584a1b2c3d4e5f6a7b8c9d1"),
  "lead_id": "GYM_20251220_0001",
  "created_at": ISODate("2024-12-20T10:30:00Z"),
  "updated_at": ISODate("2024-12-20T15:45:00Z"),

  "gym_id": 1,
  "gym_name": "Cult Andheri West",
  "partner_name": "Cult",

  "full_name": "Rajesh Kumar",
  "email": "rajesh.kumar@example.com",
  "phone": "9876543210",
  "billing_address": "Andheri West, Mumbai, Maharashtra 400053",
  "message": "Looking for evening batch, prefer 6pm onwards",

  "user_location": {
    "latitude": 19.1136,
    "longitude": 72.8697,
    "city": "Mumbai"
  },

  "status": "contacted",
  "preferred_plan": "3-month",

  "assigned_to": "agent@example.com",
  "assigned_to_name": "Nikhil Sharma",
  "assigned_at": ISODate("2024-12-20T11:00:00Z"),

  "payment": {
    "status": "link_shared",
    "amount": 4200,
    "payment_link": "https://razorpay.me/demo/abc123",
    "updated_at": ISODate("2024-12-20T15:30:00Z")
  },

  "comments": [
    {
      "timestamp": ISODate("2024-12-20T11:30:00Z"),
      "user": "agent@example.com",
      "text": "Called customer, confirmed interest in 3-month plan"
    },
    {
      "timestamp": ISODate("2024-12-20T15:30:00Z"),
      "user": "agent@example.com",
      "text": "Sent payment link via WhatsApp"
    }
  ],

  "audit_log": [
    {
      "timestamp": ISODate("2024-12-20T11:00:00Z"),
      "action": "status_change",
      "user": "agent@example.com",
      "old_value": "new",
      "new_value": "contacted",
      "reason": "First contact made"
    },
    {
      "timestamp": ISODate("2024-12-20T11:30:00Z"),
      "action": "comment_added",
      "user": "agent@example.com",
      "comment": "Called customer, confirmed interest in 3-month plan"
    },
    {
      "timestamp": ISODate("2024-12-20T15:30:00Z"),
      "action": "payment_update",
      "user": "agent@example.com",
      "old_status": "pending",
      "new_status": "link_shared",
      "amount": 4200,
      "payment_link": "https://razorpay.me/demo/abc123"
    }
  ]
}
```

### Indexes

```javascript
db.leads.createIndex({ "lead_id": 1 }, { unique: true });  // Unique lead ID
db.leads.createIndex({ "created_at": -1 });                // Sort by creation date (descending)
db.leads.createIndex({ "status": 1 });                     // Filter by status
db.leads.createIndex({ "payment.status": 1 });             // Filter by payment status
```

### Enumerations

#### `status` (Lead Status)
- `new` - Lead just created
- `contacted` - Admin/agent has contacted
- `interested` - User confirmed interest
- `not_interested` - User not interested
- `closed` - Lead closed/completed

#### `payment.status` (Payment Status)
- `pending` - Payment not initiated
- `link_shared` - Payment link sent to user
- `paid` - Payment completed
- `failed` - Payment failed

#### `preferred_plan` (Subscription Plan)
- `1-month` - 1 month subscription
- `3-month` - 3 month subscription
- `6-month` - 6 month subscription (if available)
- `12-month` - 12 month subscription

### Notes
- `lead_id` format: `GYM_YYYYMMDD_XXXX` (e.g., `GYM_20251220_0001`)
- `audit_log` captures every change to the lead
- Auto-assignment: Lead assigned to user who views/edits it
- Denormalized gym data for performance (no joins needed)

---

## Collection 3: `partners`

### Purpose
Stores partner metadata (logo, description). Partners can exist in `gyms` without being in this collection.

### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Yes | MongoDB auto-generated ID |
| `name` | String | Yes | Partner name (unique) |
| `description` | String | No | Partner description |
| `icon` | String | No | Emoji or base64 encoded image |
| `created_at` | Date | Yes | Creation timestamp |
| `updated_at` | Date | No | Last update timestamp |

### Sample Document

```javascript
{
  "_id": ObjectId("6584a1b2c3d4e5f6a7b8c9d2"),
  "name": "Cult",
  "description": "India's largest fitness chain with 100+ centers across major cities. Offers group classes, personal training, and state-of-the-art equipment.",
  "icon": "🏋️",
  "created_at": ISODate("2024-01-01T00:00:00Z"),
  "updated_at": ISODate("2024-06-15T10:00:00Z")
}
```

### Indexes

```javascript
db.partners.createIndex({ "name": 1 }, { unique: true });  // Unique partner name
```

### Notes
- This collection is optional
- If partner exists in `gyms` but not here, it will show without description/icon
- Used for displaying partner cards on frontend

---

## Collection 4: `users`

### Purpose
Stores admin and agent accounts for the admin panel.

### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Yes | MongoDB auto-generated ID |
| `email` | String | Yes | User email (unique, used for login) |
| `name` | String | Yes | Full name |
| `password_hash` | String | Yes | Bcrypt hashed password |
| `role` | String | Yes | User role (enum) |
| `is_active` | Boolean | Yes | Account active status |
| `created_at` | Date | Yes | Account creation timestamp |
| `created_by` | String | No | Email of user who created this account |
| `last_login` | Date | No | Last successful login |
| `login_count` | Integer | Yes | Total login count (default: 0) |
| `updated_at` | Date | No | Last update timestamp |
| `password_updated_at` | Date | No | Last password change timestamp |
| `deactivated_at` | Date | No | Deactivation timestamp |
| `deactivated_by` | String | No | Email of user who deactivated account |

### Sample Document

```javascript
{
  "_id": ObjectId("6584a1b2c3d4e5f6a7b8c9d3"),
  "email": "agent@example.com",
  "name": "Nikhil Sharma",
  "password_hash": "$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJK",
  "role": "agent",
  "is_active": true,
  "created_at": ISODate("2024-06-01T00:00:00Z"),
  "created_by": "admin@example.com",
  "last_login": ISODate("2024-12-20T09:15:00Z"),
  "login_count": 127,
  "updated_at": ISODate("2024-12-20T09:15:00Z"),
  "password_updated_at": ISODate("2024-11-01T14:30:00Z")
}
```

### Indexes

```javascript
db.users.createIndex({ "email": 1 }, { unique: true });  // Unique email
db.users.createIndex({ "is_active": 1 });                // Filter active users
```

### Enumerations

#### `role` (User Role)
- `admin` - Full access (create users, manage gyms, view all leads)
- `agent` - Limited access (view/edit leads, cannot create users)
- `viewer` - Read-only access (view leads only)

### Notes
- Passwords are hashed using bcrypt (cost factor 12)
- Default admin created on first startup from `.env` file
- Soft delete: `is_active = false` instead of deletion
- Only admins can deactivate other users
- Admin users cannot be deactivated

---

## Relationships

### Gyms ← Leads
- **Type**: One-to-Many (One gym can have many leads)
- **Foreign Key**: `leads.gym_id` references `gyms.gym_id`
- **Implementation**: Denormalized (gym name/partner stored in leads)

### Users ← Leads
- **Type**: One-to-Many (One user can be assigned to many leads)
- **Foreign Key**: `leads.assigned_to` references `users.email`
- **Implementation**: Soft reference (email string)

### Partners ← Gyms
- **Type**: One-to-Many (One partner can have many gyms)
- **Foreign Key**: `gyms.partner_name` references `partners.name`
- **Implementation**: Soft reference (name string)

---

## Data Integrity Rules

1. **Gym ID Uniqueness**: `gym_id` must be unique and auto-incremented
2. **Lead ID Format**: Must follow `GYM_YYYYMMDD_XXXX` pattern
3. **Phone Validation**: 10 digits, starts with 6/7/8/9
4. **Pincode Validation**: 6 digits
5. **GeoJSON Format**: `location.type` must be "Point", coordinates must be [lon, lat]
6. **Email Uniqueness**: User emails must be unique
7. **Soft Deletes**: Never hard delete gyms or users
8. **Audit Trail**: Every lead change must be logged in `audit_log`

---

## Sample Data Seeding

### Create Sample Gym

```javascript
db.gyms.insertOne({
  "gym_id": 1,
  "gym_name": "Cult Andheri West",
  "partner_name": "Cult",
  "address": "Plot 123, Veera Desai Road, Andheri West",
  "city": "Mumbai",
  "state": "Maharashtra",
  "pincode": "400053",
  "latitude": 19.1136,
  "longitude": 72.8697,
  "location": {
    "type": "Point",
    "coordinates": [72.8697, 19.1136]
  },
  "amenities": ["AC", "Parking", "Showers", "Lockers"],
  "subscription_amount": 1499,
  "icon": "🏋️",
  "is_active": true,
  "created_at": new Date()
});
```

### Create Sample Partner

```javascript
db.partners.insertOne({
  "name": "Cult",
  "description": "India's largest fitness chain",
  "icon": "🏋️",
  "created_at": new Date()
});
```

---

## Query Examples

### Find Gyms Near Location

```javascript
db.gyms.find({
  "location": {
    "$near": {
      "$geometry": {
        "type": "Point",
        "coordinates": [72.8697, 19.1136]  // [lon, lat]
      },
      "$maxDistance": 5000  // 5km in meters
    }
  },
  "is_active": true
}).limit(10);
```

### Find Gyms by Pincode

```javascript
db.gyms.find({
  "pincode": "400053",
  "is_active": true
});
```

### Get All Leads with Status "new"

```javascript
db.leads.find({
  "status": "new"
}).sort({ "created_at": -1 });
```

### Get Leads with Payment Status "paid"

```javascript
db.leads.find({
  "payment.status": "paid"
});
```

---

## Backup & Recovery

### Backup Command (mongodump)

```bash
mongodump --uri="mongodb+srv://username:password@cluster.mongodb.net/gym_habit" --out=/backup/$(date +%Y%m%d)
```

### Restore Command (mongorestore)

```bash
mongorestore --uri="mongodb+srv://username:password@cluster.mongodb.net/gym_habit" /backup/20251220/gym_habit
```

---

## Performance Considerations

### Expected Document Sizes
- **Gym**: ~500 bytes average
- **Lead**: ~2KB average (with audit trail)
- **Partner**: ~200 bytes
- **User**: ~300 bytes

### Storage Estimates
- **10,000 gyms**: ~5MB
- **50,000 leads**: ~100MB
- **Total (10k gyms + 50k leads)**: ~105MB

### Query Performance
- **Nearby gyms**: <50ms (with 2dsphere index)
- **Pincode search**: <10ms (with pincode index)
- **Lead listing**: <100ms (with created_at index)

### Recommended Scaling
- **Up to 100k gyms**: Single instance sufficient
- **100k+ gyms**: Consider sharding
- **High write volume**: Enable replica set

---

## End of Database Schema Documentation
