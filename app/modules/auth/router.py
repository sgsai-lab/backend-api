from fastapi import APIRouter

# Signup, login, Google sign-in, password reset, MFA: see API-07..API-11.
router = APIRouter(prefix="/auth", tags=["auth"])
