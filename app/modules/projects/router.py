from fastapi import APIRouter

# Project CRUD scoped to the authenticated owner: see API-13.
router = APIRouter(prefix="/projects", tags=["projects"])
