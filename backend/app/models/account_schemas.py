from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, UUID4, field_validator

Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{2,31}$")]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) and value.isascii() else value

    @field_validator("password")
    @classmethod
    def utf8_password(cls, value):
        value.encode("utf-8")
        return value


class RegisterInput(AccountInput):
    password: Annotated[str, StringConstraints(min_length=15, max_length=128)]


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: DisplayName

    @field_validator("display_name")
    @classmethod
    def printable(cls, value):
        if not value.isprintable():
            raise ValueError("Display names must be printable")
        return value


class CurrentAccount(BaseModel):
    id: UUID4
    username: str
    display_name: str
    created_at: datetime

    @classmethod
    def from_user(cls, user):
        created_at = user.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return cls(id=user.id, username=user.username,
                   display_name=user.display_name or user.username, created_at=created_at)
