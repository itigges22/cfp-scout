"""GET /api/v1/me — return the authenticated user's identity."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["auth"])


class UserRead(BaseModel):
    email: str


@router.get("/me", response_model=UserRead)
async def get_me(request: Request) -> UserRead:
    return UserRead(email=getattr(request.state, "user_email", ""))
