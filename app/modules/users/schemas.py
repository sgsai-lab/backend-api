import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.core.pagination import PageParams
from app.modules.auth.schemas import FullName, StrictModel
from app.modules.users.models import UserRole, UserStatus

UserSort = Literal["created_at", "-created_at", "email", "-email", "full_name", "-full_name"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    avatar_url: str | None
    role: UserRole
    status: UserStatus
    email_verified: bool
    mfa_enabled: bool
    created_at: datetime
    last_login_at: datetime | None


class UserUpdateMe(StrictModel):
    full_name: FullName | None = None
    avatar_url: Annotated[HttpUrl, Field(max_length=2048)] | None = None


class AdminUserCreate(StrictModel):
    email: EmailStr
    full_name: FullName
    role: UserRole = UserRole.USER


class AdminUserUpdate(StrictModel):
    full_name: FullName | None = None
    role: UserRole | None = None
    status: UserStatus | None = None


class UserListParams(PageParams):
    status: UserStatus | None = None
    role: UserRole | None = None
    q: Annotated[str, Field(max_length=100)] | None = None
    sort: UserSort = "-created_at"
