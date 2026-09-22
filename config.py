"""
Gym Habit - Configuration
Environment variables and settings
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# MongoDB Configuration
MONGODB_URL: str = os.getenv(
    "MONGODB_URL",
    "mongodb://localhost:27017"  # Local development fallback
)
MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "gym_demo")

# JWT Configuration
JWT_SECRET_KEY: str = os.getenv(
    "JWT_SECRET_KEY",
    "your-secret-key-change-in-production-please-make-it-long-and-random"
)
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRATION_HOURS: int = 24  # Token expires in 24 hours

# Google API
GOOGLE_GEOCODING_API_KEY: Optional[str] = os.getenv("GOOGLE_GEOCODING_API_KEY", "")

# Admin Configuration
DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
DEFAULT_ADMIN_PASSWORD: str = "Demo@12345"  # Change after first login
DEFAULT_ADMIN_NAME: str = "Admin User"

# Application Settings
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
DEBUG: bool = ENVIRONMENT == "development"

# Pagination
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# Lead ID Configuration
LEAD_ID_PREFIX: str = "GYM"

# CSV Export Configuration
CSV_FILENAME_PREFIX: str = "gym_habit_leads"
