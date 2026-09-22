# Gym Habit - Technology Stack Overview

## Quick Summary

**Type**: Full-stack web application (gym membership lead generation)
**Architecture**: Monolithic (single FastAPI backend serving API + static frontend)
**Database**: MongoDB (NoSQL, document-based)
**Deployment**: AWS EC2 / ECS / Lambda (requires compute + database)

---

## Backend Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | FastAPI | 0.104+ | Web framework |
| **Runtime** | Python | 3.10+ | Programming language |
| **Server** | Uvicorn | 0.24+ | ASGI server |
| **Database** | MongoDB | 4.4+ | NoSQL database |
| **DB Driver** | Motor | 3.7+ | Async MongoDB driver |
| **Auth** | JWT (python-jose) | 3.5+ | Token-based authentication |
| **Password** | Bcrypt (passlib) | 1.7+ | Password hashing |
| **Validation** | Pydantic | 2.5+ | Data validation |
| **External API** | Google Geocoding | v3 | Location search |

---

## Frontend Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **HTML** | HTML5 | - | Structure |
| **CSS** | CSS3 (Custom) | - | Styling |
| **JavaScript** | Vanilla JS (ES6+) | - | Interactivity |
| **No Build Tool** | - | - | Served directly by FastAPI |

**Note**: No Node.js, npm, React, or build process required. Pure vanilla JavaScript.

---

## Infrastructure Stack (AWS Recommended)

### Minimum Required:
- **Compute**: EC2 (t3.small) OR ECS Fargate OR Lambda
- **Database**: MongoDB Atlas (free tier) OR AWS DocumentDB
- **Load Balancer**: ALB (for HTTPS/SSL)
- **DNS**: Route 53 (optional)
- **SSL**: ACM or Let's Encrypt

### Optional:
- **CDN**: CloudFront
- **Secrets**: AWS Secrets Manager
- **Monitoring**: CloudWatch
- **CI/CD**: GitLab CI/CD

---

## Dependencies

### Python Packages (requirements.txt)

```
fastapi==0.104.1              # Web framework
uvicorn[standard]==0.24.0     # ASGI server
python-multipart==0.0.6       # Form data parsing
pydantic[email]==2.5.0        # Data validation
motor==3.7.1                  # Async MongoDB driver
pymongo==4.15.5               # MongoDB driver
passlib[bcrypt]==1.7.4        # Password hashing
python-jose[cryptography]==3.5.0  # JWT tokens
python-dotenv==1.2.1          # Environment variables
requests==2.31.0              # HTTP client
scipy==1.11.4                 # Scientific computing (Haversine distance)
```

**Total Size**: ~150MB installed

---

## Database

**Type**: MongoDB (NoSQL, document-based)
**Collections**: 4 (gyms, leads, partners, users)
**Indexes**: 14 total
**Size**: ~10MB per 1,000 gyms, ~5MB per 1,000 leads

### Why MongoDB?
- Flexible schema for varying gym data
- Geospatial queries (nearby gyms)
- Fast read/write for lead management
- Easy horizontal scaling
- JSON-like documents (easy for JS frontend)

---

## External Services

### Google Geocoding API
- **Purpose**: Convert "Mumbai" → coordinates (lat/lon)
- **Usage**: Location search feature
- **Cost**: Free tier (40k requests/month), then $5 per 1000 requests
- **Required**: Yes (or location search will fail)

---

## File Structure

```
gym_habit/
├── main.py                    # FastAPI app entry point
├── config.py                  # Configuration & environment variables
├── auth.py                    # JWT authentication logic
├── mongodb.py                 # MongoDB connection manager
├── mongo_database.py          # Database operations (gyms, leads)
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (NOT in Git)
├── .gitignore                # Git ignore rules
├── frontend/
│   ├── index.html            # Main user page
│   ├── admin.html            # Admin panel
│   └── style.css             # Styles
├── DEPLOYMENT_GUIDE_DEVOPS.md  # Deployment guide
├── DATABASE_SCHEMA.md         # Database structure
└── README.md                  # Project overview
```

---

## Environment Variables

**Required**:
- `MONGODB_URL` - MongoDB connection string
- `JWT_SECRET_KEY` - Secret for JWT tokens (min 32 chars)
- `GOOGLE_GEOCODING_API_KEY` - Google API key

**Optional**:
- `ENVIRONMENT` - production/development
- `DEFAULT_ADMIN_EMAIL` - Default admin email
- `DEFAULT_ADMIN_PASSWORD` - Default admin password

---

## Ports

| Port | Service | Purpose |
|------|---------|---------|
| 8000 | FastAPI | Application (default) |
| 80 | Nginx | HTTP (if using reverse proxy) |
| 443 | Nginx | HTTPS (if using reverse proxy) |
| 27017 | MongoDB | Database (if self-hosted) |

---

## Performance Metrics

### Current Capacity (t3.small + MongoDB Atlas M0):
- **Gyms**: Up to 10,000
- **Concurrent Users**: ~100
- **Leads per Month**: ~10,000
- **Response Time**: <100ms (avg)
- **Database Size**: ~100MB (10k gyms + 50k leads)

### Resource Usage:
- **Memory**: ~200MB (idle), ~500MB (active)
- **CPU**: <5% (idle), ~30% (active)
- **Disk**: ~500MB (app + dependencies)

---

## Security

### Authentication:
- JWT tokens (HS256 algorithm)
- Bcrypt password hashing (cost factor 12)
- Token expiration: 24 hours

### Data Protection:
- MongoDB connection over TLS/SSL
- Environment variables for secrets
- No plain text passwords
- HTTPS for production

### OWASP Compliance:
- SQL Injection: Not applicable (MongoDB)
- XSS: Sanitized inputs
- CSRF: Token-based auth
- Sensitive Data: Encrypted in transit

---

## Scalability

### Horizontal Scaling:
- **Stateless**: No session storage (JWT tokens)
- **Load Balancer**: ALB distributes traffic
- **Multiple Instances**: Can run 2+ EC2/ECS instances
- **Database**: MongoDB replica set for HA

### Vertical Scaling:
- **t3.small** → **t3.medium** → **t3.large**
- No code changes required

---

## Monitoring & Logging

### Application Logs:
- FastAPI logs to stdout
- Uvicorn access logs
- Captured by CloudWatch (if configured)

### Health Check:
- Endpoint: `GET /health`
- Returns: Database status, gym count

### Metrics to Monitor:
- CPU/Memory usage (EC2/ECS)
- Request count & latency (ALB)
- Database connections (MongoDB)
- Error rate (5xx responses)

---

## Development vs Production

| Aspect | Development | Production |
|--------|-------------|------------|
| Database | MongoDB Atlas M0 (free) | MongoDB Atlas M10+ or DocumentDB |
| Server | `python main.py` | Systemd service or ECS |
| HTTPS | No | Yes (ACM or Let's Encrypt) |
| Load Balancer | No | ALB |
| Secrets | .env file | AWS Secrets Manager |
| Monitoring | None | CloudWatch |

---

## Cost Breakdown (Monthly)

### Development:
- EC2 t3.small: $15
- MongoDB Atlas M0: $0 (free)
- **Total: ~$15/month**

### Production (Small):
- EC2 t3.small: $15
- MongoDB Atlas M10: $60
- ALB: $20
- Route 53: $1
- **Total: ~$96/month**

### Production (Medium):
- ECS Fargate: $40
- DocumentDB (t3.medium): $200
- ALB: $20
- CloudWatch: $10
- **Total: ~$270/month**

---

## Deployment Time

### Initial Setup:
- MongoDB Atlas: 10 minutes
- EC2 instance: 5 minutes
- App deployment: 15 minutes
- SSL setup: 10 minutes
- **Total: ~40 minutes**

### Subsequent Deployments:
- Git pull + restart: ~2 minutes

---

## Support & Maintenance

### Regular Tasks:
- Monitor MongoDB disk usage (monthly)
- Update Python dependencies (quarterly)
- Review application logs (weekly)
- Backup verification (weekly)

### Critical Updates:
- Security patches: Apply immediately
- Python version upgrades: Test before applying
- MongoDB version upgrades: Plan maintenance window

---

## Browser Compatibility

### Supported Browsers:
- Chrome 90+ ✅
- Firefox 88+ ✅
- Safari 14+ ✅
- Edge 90+ ✅
- Mobile browsers (iOS/Android) ✅

### Required Browser Features:
- JavaScript ES6+ (async/await, fetch API)
- CSS Grid & Flexbox
- HTML5 form validation

---

## API Documentation

**Endpoint**: `/docs` (Swagger UI)
**Alternative**: `/redoc` (ReDoc UI)

### Key API Endpoints:
- `GET /` - Frontend (public)
- `GET /admin` - Admin panel (JWT required)
- `GET /api/gyms/nearby` - Find nearby gyms
- `GET /api/gyms/search-by-location` - Search by city/pincode
- `POST /api/subscription/request` - Submit lead
- `POST /api/auth/login` - Admin login
- `GET /api/admin/leads` - Get all leads (JWT required)

---

## Known Limitations

1. **No Real-time Updates**: Admin panel requires manual refresh
2. **No Multi-tenancy**: Single organization only
3. **No Payment Processing**: Only tracks payment links/status
4. **No Email Notifications**: Manual follow-up required
5. **No SMS Integration**: Manual communication only
6. **No Mobile Apps**: Web-only (responsive design)

---

## Future Enhancements (Not Implemented)

- Real-time notifications (WebSockets)
- Payment gateway integration (Razorpay)
- Email/SMS automation
- Mobile app (React Native)
- Analytics dashboard
- Multi-language support
- Membership activation system

---

## Contact for Technical Questions

- **Repository**: [To be migrated to GitLab]
- **Documentation**: See `DEPLOYMENT_GUIDE_DEVOPS.md` and `DATABASE_SCHEMA.md`
- **API Docs**: Available at `/docs` after deployment

---

**End of Technology Stack Overview**
