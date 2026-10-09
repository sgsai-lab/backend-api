import json
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.pagination import PageParams
from app.modules.projects.models import ProjectStatus

METADATA_MAX_BYTES = 16 * 1024


def _dedupe(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


def _metadata_size(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, separators=(",", ":")).encode()) > METADATA_MAX_BYTES:
        raise ValueError("metadata must be at most 16 KB")
    return value


Tag = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=32)
]
Tags = Annotated[list[Tag], Field(max_length=20), AfterValidator(_dedupe)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, Field(max_length=5000)]
Metadata = Annotated[dict[str, Any], AfterValidator(_metadata_size)]
ProjectSort = Literal["created_at", "-created_at", "name", "-name", "updated_at", "-updated_at"]


def _check_dates(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("end_date must be on or after start_date")


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Name
    description: Description | None = None
    status: ProjectStatus = ProjectStatus.DRAFT
    tags: Tags = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        _check_dates(self.start_date, self.end_date)
        return self


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Name | None = None
    description: Description | None = None
    status: ProjectStatus | None = None
    tags: Tags | None = None
    start_date: date | None = None
    end_date: date | None = None
    metadata: Metadata | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        for field in ("name", "status", "tags", "metadata"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        _check_dates(self.start_date, self.end_date)
        return self


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    tags: list[str]
    start_date: date | None
    end_date: date | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ProjectFilters(PageParams):
    status: ProjectStatus | None = None
    tag: list[Annotated[str, StringConstraints(to_lower=True, max_length=32)]] = Field(
        default_factory=list, max_length=20
    )
    q: Annotated[str, Field(max_length=100)] | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    owner_id: uuid.UUID | None = Field(default=None, description="Admins only")
    sort: ProjectSort = "-created_at"
