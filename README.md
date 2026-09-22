# Gym Finder — Partner Gym Membership Portal

A full-stack web application for discovering partner gyms, submitting membership interest, and managing the resulting sales pipeline end to end. Built as a real production system: a public gym-finder site plus an internal portal where a sales team works every enquiry through to a recorded payment.

> **Demo project.** All data here is sample data and all credentials are placeholders.

---

## What it does

**For the customer (public site)**
- Find gyms by 6-digit PIN code, by city, or by free-text place search (Google Geocoding + MongoDB geospatial `$near`)
- Browse partner brands, amenities and per-gym pricing plans with discounts
- Pick a plan and submit interest — which creates a lead and sends an automatic acknowledgement email

**For the sales team (admin portal)**
- Leads table with filters (status, payment, city, owner, date range) and CSV export
- Every new lead is auto-assigned to an agent by an atomic round-robin counter
- Work a lead: status changes, internal comments, plan upgrades, payment recording, invoice number
- Five transactional email templates (acknowledgement, follow-up, payment confirmation, interim info, closure) with per-lead rate limits and an admin-managed CC list
- Gym & partner management, including bulk CSV upload that upserts by centre code
- Full audit trail of every change on every lead

---

## Design highlights

- **Role-based access.** Two roles: `admin` (full access) and `agent` (may only modify leads assigned to them). Ownership is enforced server-side on every write.
- **A payment state machine.** Once a payment is recorded as paid the plan locks, and the only remaining status transition is to "Activated", which is final.
- **Reconciliation IDs.** Marking a lead paid with a unique reference mints a sequential `HHGYM-00001` recon ID from an atomic MongoDB counter, used to match payments to invoices.
- **Snapshot semantics.** A lead stores the gym name and plan it was created with, so later catalogue edits never rewrite history.
- **Timezone-correct filtering.** Records are stored in UTC but filtered by IST calendar days, so the table and the CSV export always agree.
- **Defensive details.** CSV-injection sanitising on export, HTML escaping on all user-supplied text, bcrypt password hashing, JWT auth, and a partial unique index that blocks duplicate payment references under concurrency.

---

## Tech stack

| Layer | Choice |
|---|---|
| API | Python 3.9+, FastAPI, Uvicorn |
| Data | MongoDB (Motor async driver), geospatial 2dsphere index |
| Auth | JWT (python-jose) + bcrypt |
| Frontend | Vanilla HTML/CSS/JS — no build step, no framework |
| Email | SendGrid |
| Maps | Google Maps JS + Places (browser), Google Geocoding (server) |

---

## Run it locally

Requires Python 3.9+ and MongoDB running on `localhost:27017`.

```bash
git clone https://github.com/nikhil13dubey-star/GYM_demo.git
cd GYM_demo

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # optional: add your own API keys
python seed_demo_data.py      # loads 30 sample gyms + 4 demo users (clears the demo DB first)
uvicorn main:app --reload
```

- Public site: http://localhost:8000
- Admin portal: http://localhost:8000/admin
- API docs (auto-generated): http://localhost:8000/docs

### Demo logins

| Role | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `Demo@12345` |
| Agent | `nikhil@example.com` | `Demo@12345` |

### Optional API keys

The app runs fine without them. Add to `.env` to enable the extras:

- `GOOGLE_GEOCODING_API_KEY` — city and free-text location search. Without it those searches return an error; **PIN-code search and browsing work fully without any key**
- `SENDGRID_API_KEY` — actually sending email (without it, sends are logged and reported as not configured)
- A Google Maps browser key in `frontend/index.html` — map autocomplete (falls back to local suggestions)

---

## Project structure

```
main.py               FastAPI app — 47 routes (public, auth, admin)
mongo_database.py     Domain logic: gym catalogue + lead lifecycle
mongodb.py            Connection and index setup
auth.py               JWT issue/verify, password hashing
communications.py     Email playbook, CC settings, communications log
email_service.py      SendGrid templates and delivery
config.py             Environment-driven settings
seed_demo_data.py     Loads the sample dataset
frontend/index.html   Public gym finder (single page)
frontend/admin.html   Admin + agent portal
gyms.csv              30 sample gyms
test_*.py             Integration test suites
```

## Tests

With the server running against a **test** database:

```bash
python test_features.py          # core feature suite
python test_rbac.py              # role & ownership rules
python test_communications.py    # email rules, CC management, logging
python test_date_filters.py      # IST date filtering, table/export parity
```

---
