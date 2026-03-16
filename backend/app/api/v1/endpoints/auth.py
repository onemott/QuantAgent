"""
Authentication Endpoints
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter()


class UserLogin(BaseModel):
    username: str
    password: str


class UserRegister(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """
    User login (simulated for MVP)
    """
    # TODO: Implement actual authentication
    return TokenResponse(
        access_token="simulated-jwt-token",
        expires_in=1800
    )


@router.post("/register")
async def register(user: UserRegister):
    """
    User registration (simulated for MVP)
    """
    # TODO: Implement actual registration
    return {
        "message": "User registered successfully",
        "user_id": "simulated-user-id"
    }


@router.get("/me")
async def get_current_user():
    """
    Get current user info
    """
    return {
        "user_id": "simulated-user-id",
        "email": "user@example.com",
        "username": "trader001"
    }
