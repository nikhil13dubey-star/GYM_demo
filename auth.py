"""
Gym Habit - Authentication Utilities
JWT tokens and password hashing
"""

from datetime import datetime, timedelta
from typing import Optional, Dict
import bcrypt
from jose import JWTError, jwt
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import config

# HTTP Bearer for token extraction
security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    # Ensure password is bytes and within bcrypt limit (72 bytes)
    password_bytes = password[:72].encode('utf-8')
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    password_bytes = plain_password[:72].encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Dictionary with user data (user_id, email, role)
        expires_delta: Optional expiration time

    Returns:
        JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=config.JWT_EXPIRATION_HOURS)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM
    )

    return encoded_jwt


def decode_access_token(token: str) -> Dict:
    """
    Decode and verify a JWT token

    Args:
        token: JWT token string

    Returns:
        Dictionary with user data

    Raises:
        HTTPException if token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM]
        )
        return payload

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Get current authenticated user from JWT token

    Args:
        credentials: HTTP Bearer credentials from request header

    Returns:
        Dictionary with user data

    Raises:
        HTTPException if authentication fails
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    return payload


def require_role(*allowed_roles: str):
    """
    Decorator to check if user has required role

    Usage:
        @require_role("admin")
        async def admin_only_endpoint(current_user: Dict = Depends(get_current_user)):
            pass

        @require_role("admin", "facilitator")
        async def facilitator_endpoint(current_user: Dict = Depends(get_current_user)):
            pass
    """
    def decorator(func):
        async def wrapper(*args, current_user: Dict = Depends(get_current_user), **kwargs):
            user_role = current_user.get("role")

            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access forbidden. Required role: {', '.join(allowed_roles)}"
                )

            return await func(*args, current_user=current_user, **kwargs)

        return wrapper

    return decorator
