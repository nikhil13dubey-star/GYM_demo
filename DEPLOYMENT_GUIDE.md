# AWS EC2 Deployment Guide
**Gym Habit - Demo Webapp**

This guide provides step-by-step instructions for deploying the Gym Habit application to AWS EC2.

---

## Prerequisites

Before you begin, ensure you have:

- [ ] AWS Account with EC2 access
- [ ] SSH Key Pair for EC2 access (.pem file)
- [ ] (Optional) Domain name for the application
- [ ] Git repository with project code
- [ ] Basic knowledge of Linux command line

**Estimated Time:** 30-45 minutes

**Monthly Cost:** ~$8-10 (t2.micro instance)

---

## Deployment Architecture

```
User Browser
      ↓
   Internet
      ↓
AWS EC2 Instance (Ubuntu 22.04)
├── Nginx (Port 80/443) → Reverse Proxy
│   └── SSL Certificate (Let's Encrypt)
└── FastAPI App (Port 8000)
    ├── main.py
    ├── database.py
    ├── gyms.csv
    └── frontend/
```

---

## Step 1: Launch EC2 Instance

### 1.1 AWS Console Setup

1. Log in to [AWS Console](https://console.aws.amazon.com)
2. Navigate to **EC2 Dashboard**
3. Click **"Launch Instance"**

### 1.2 Instance Configuration

**Name:** `gym-habit-server`

**OS Image:**
- Ubuntu Server 22.04 LTS (HVM), SSD Volume Type
- Architecture: 64-bit (x86)

**Instance Type:**
- **t2.micro** (1 vCPU, 1 GB RAM)
- Free tier eligible
- Sufficient for 1,000-2,000 users/month

**Key Pair:**
- Select existing key pair OR
- Create new key pair
- Download .pem file and keep it safe

**Network Settings:**
- Create security group with following rules:

| Type | Protocol | Port | Source | Description |
|------|----------|------|--------|-------------|
| SSH | TCP | 22 | Your IP | SSH access |
| HTTP | TCP | 80 | 0.0.0.0/0 | Web access |
| HTTPS | TCP | 443 | 0.0.0.0/0 | Secure web |

**Storage:**
- 8 GB gp2 (General Purpose SSD)
- Default is sufficient

### 1.3 Launch Instance

1. Review configuration
2. Click **"Launch instance"**
3. Wait for instance to be "Running"
4. Note down **Public IPv4 address**

---

## Step 2: Connect to EC2 Instance

### 2.1 Windows (Using Git Bash or PowerShell)

```bash
ssh -i path/to/keypair.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

### 2.2 Mac/Linux

```bash
chmod 400 path/to/keypair.pem
ssh -i path/to/keypair.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

### 2.3 Verify Connection

You should see:
```
Welcome to Ubuntu 22.04 LTS
ubuntu@ip-xxx-xxx-xxx-xxx:~$
```

---

## Step 3: Install Dependencies

### 3.1 Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### 3.2 Install Python 3

```bash
sudo apt install python3 python3-pip -y
python3 --version  # Should show 3.10+
```

### 3.3 Install Git

```bash
sudo apt install git -y
git --version
```

### 3.4 Install Nginx (Web Server)

```bash
sudo apt install nginx -y
sudo systemctl status nginx
```

---

## Step 4: Clone Project Repository

### 4.1 Navigate to Home Directory

```bash
cd /home/ubuntu
```

### 4.2 Clone Git Repository

**Option A: Using HTTPS**
```bash
git clone https://github.com/YOUR_ORG/gym_habit.git
```

**Option B: Upload Files via SCP**

From your local machine:
```bash
scp -i keypair.pem -r gym_habit/ ubuntu@YOUR_EC2_IP:/home/ubuntu/
```

### 4.3 Verify Files

```bash
cd gym_habit
ls -la
```

You should see:
```
main.py
database.py
gyms.csv
requirements.txt
frontend/
```

---

## Step 5: Install Python Dependencies

```bash
cd /home/ubuntu/gym_habit
pip3 install -r requirements.txt
```

Wait for installation to complete.

---

## Step 6: Test Application Manually

### 6.1 Run Server

```bash
python3 main.py
```

You should see:
```
============================================================
GYM HABIT - Demo Webapp Partner Gym Finder
============================================================
[OK] Loaded 30 gyms from database
[OK] Available partners: 5
...
```

### 6.2 Test from Browser

1. Open browser
2. Navigate to: `http://YOUR_EC2_PUBLIC_IP:8000`
3. You should see the Gym Habit homepage

### 6.3 Stop Server

Press `CTRL + C` to stop the server.

---

## Step 7: Create Systemd Service (Run 24/7)

### 7.1 Create Service File

```bash
sudo nano /etc/systemd/system/gym_habit.service
```

### 7.2 Paste Configuration

```ini
[Unit]
Description=Gym Habit FastAPI Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/gym_habit
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save:** Press `CTRL + X`, then `Y`, then `ENTER`

### 7.3 Enable and Start Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable gym_habit
sudo systemctl start gym_habit
```

### 7.4 Check Status

```bash
sudo systemctl status gym_habit
```

Should show:
```
● gym_habit.service - Gym Habit FastAPI Server
   Loaded: loaded
   Active: active (running)
```

### 7.5 View Logs

```bash
sudo journalctl -u gym_habit -f
```

Press `CTRL + C` to exit logs.

---

## Step 8: Configure Nginx (Optional but Recommended)

### Why Nginx?
- Serve on port 80 (users don't need to type :8000)
- Enable HTTPS/SSL
- Better performance
- Load balancing (future)

### 8.1 Create Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/gym_habit
```

### 8.2 Paste Configuration

```nginx
server {
    listen 80;
    server_name YOUR_EC2_PUBLIC_IP;  # Or your domain name

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Save and exit.**

### 8.3 Enable Site

```bash
sudo ln -s /etc/nginx/sites-available/gym_habit /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl reload nginx
```

### 8.4 Test

Navigate to: `http://YOUR_EC2_PUBLIC_IP` (no port number)

You should see the Gym Habit application!

---

## Step 9: Setup SSL Certificate (HTTPS) - Optional

### 9.1 Install Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
```

### 9.2 Obtain Certificate

**Prerequisites:**
- Must have a domain name (e.g., gym.example.com)
- Domain DNS must point to EC2 Public IP

**Command:**
```bash
sudo certbot --nginx -d yourdomain.com
```

**Follow prompts:**
1. Enter email address
2. Agree to terms
3. Choose: Redirect HTTP to HTTPS (recommended)

### 9.3 Test HTTPS

Navigate to: `https://yourdomain.com`

Certificate auto-renews every 90 days.

---

## Step 10: Update Application

### When you need to update the app:

```bash
cd /home/ubuntu/gym_habit
git pull origin main  # Pull latest code
sudo systemctl restart gym_habit  # Restart service
```

---

## Step 11: Manage the Service

### Check if running
```bash
sudo systemctl status gym_habit
```

### Start service
```bash
sudo systemctl start gym_habit
```

### Stop service
```bash
sudo systemctl stop gym_habit
```

### Restart service
```bash
sudo systemctl restart gym_habit
```

### View logs
```bash
sudo journalctl -u gym_habit -n 100  # Last 100 lines
sudo journalctl -u gym_habit -f       # Follow logs
```

---

## Admin Panel Access

**URL:** `http://YOUR_DOMAIN/admin` or `http://YOUR_EC2_IP/admin`

**Password:** `Demo@12345`

**Change Password:**
1. Edit `main.py` line 42
2. Change `ADMIN_PASSWORD = "Demo@12345"` to your password
3. Restart service: `sudo systemctl restart gym_habit`

**Better approach (Environment Variable):**

```bash
sudo nano /etc/systemd/system/gym_habit.service
```

Add under `[Service]`:
```ini
Environment="ADMIN_PASSWORD=your_new_password"
```

Update `main.py`:
```python
import os
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Demo@12345")
```

Reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart gym_habit
```

---

## Backup & Recovery

### Backup Gym Data

```bash
scp -i keypair.pem ubuntu@YOUR_EC2_IP:/home/ubuntu/gym_habit/gyms.csv ~/Desktop/
scp -i keypair.pem ubuntu@YOUR_EC2_IP:/home/ubuntu/gym_habit/subscription_requests.json ~/Desktop/
```

### Restore Gym Data

```bash
scp -i keypair.pem ~/Desktop/gyms.csv ubuntu@YOUR_EC2_IP:/home/ubuntu/gym_habit/
sudo systemctl restart gym_habit
```

---

## Monitoring & Maintenance

### Check Disk Space

```bash
df -h
```

### Check Memory Usage

```bash
free -h
```

### Check CPU Usage

```bash
top
```

Press `q` to exit.

### Check Application Logs

```bash
sudo journalctl -u gym_habit --since "1 hour ago"
```

---

## Troubleshooting

### Issue: Service won't start

**Check logs:**
```bash
sudo journalctl -u gym_habit -n 50
```

**Common issues:**
- Port 8000 already in use
- Python dependencies not installed
- File permissions issue

### Issue: Can't access from browser

**Check security group:**
- Ensure port 80/443 is open to 0.0.0.0/0
- Verify EC2 Public IP is correct

**Check nginx:**
```bash
sudo systemctl status nginx
sudo nginx -t
```

### Issue: 502 Bad Gateway

**Cause:** FastAPI not running

**Solution:**
```bash
sudo systemctl start gym_habit
sudo systemctl status gym_habit
```

### Issue: Changes not reflecting

**Solution:**
```bash
cd /home/ubuntu/gym_habit
git pull origin main
sudo systemctl restart gym_habit
```

---

## Cost Optimization

### Current Setup Cost Breakdown

| Service | Monthly Cost |
|---------|--------------|
| EC2 t2.micro | $8.50 |
| EBS Storage (8 GB) | $0.80 |
| Data Transfer | ~$1.00 |
| **Total** | **~$10/month** |

### Tips to Save Costs

1. **Use Free Tier:** First 12 months, t2.micro is free (750 hours/month)
2. **Reserve Instance:** Save 30-60% with 1-year commitment
3. **Stop when not needed:** Stop instance during off-hours (not recommended for production)
4. **Optimize data transfer:** Use CloudFront CDN if serving static files

---

## Scaling (Future)

### When traffic grows:

**Vertical Scaling (Upgrade instance):**
- t2.small (2 GB RAM) - ~$17/month - Handles 5,000-10,000 users
- t3.medium (4 GB RAM) - ~$30/month - Handles 20,000+ users

**Horizontal Scaling (Load Balancer):**
- Add Application Load Balancer
- Run multiple EC2 instances
- Auto-scaling group

**Database Migration:**
- Migrate from CSV to PostgreSQL (AWS RDS)
- Better for 100,000+ gyms
- ~$15-50/month for RDS db.t3.micro

---

## Security Checklist

- [ ] EC2 Security Group: Only allow necessary ports
- [ ] SSH: Use key-based authentication (no passwords)
- [ ] Admin password: Changed from default
- [ ] HTTPS: SSL certificate installed
- [ ] Firewall: UFW enabled (optional)
- [ ] Auto-updates: Enabled for security patches
- [ ] Backups: Regular backups of gyms.csv and subscription data
- [ ] Monitoring: CloudWatch alarms set up

---

## Support

For deployment issues:
- Review this guide step-by-step
- Check AWS EC2 documentation
- Review application logs
- Contact DevOps team

---

## Quick Command Reference

```bash
# Service Management
sudo systemctl status gym_habit
sudo systemctl restart gym_habit
sudo journalctl -u gym_habit -f

# Nginx Management
sudo systemctl status nginx
sudo nginx -t
sudo systemctl reload nginx

# Update Application
cd /home/ubuntu/gym_habit
git pull origin main
sudo systemctl restart gym_habit

# View Logs
sudo journalctl -u gym_habit -n 100
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Check System Resources
df -h          # Disk space
free -h        # Memory
top            # CPU usage
```

---

## Congratulations!

Your Gym Habit application is now deployed and running 24/7 on AWS EC2!

**Access URLs:**
- **Main App:** `http://YOUR_EC2_IP` or `https://yourdomain.com`
- **Admin Panel:** `http://YOUR_EC2_IP/admin`
- **API Docs:** `http://YOUR_EC2_IP/docs`

---

**Questions?** Review the README.md for application-specific documentation.
