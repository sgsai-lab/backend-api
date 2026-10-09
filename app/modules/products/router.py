from fastapi import APIRouter

# Product CRUD: see API-14.
router = APIRouter(prefix="/products", tags=["products"])
