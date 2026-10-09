from fastapi import APIRouter

# /users/me and admin user management: see API-06, API-12.
router = APIRouter(prefix="/users", tags=["users"])
