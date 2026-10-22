from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    client = "client"
    staff = "staff"
    admin = "admin"


class StaffLogin(BaseModel):
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)


class StaffUserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.staff


class ClientUserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)
    customer_id: str
    primary_vehicle_id: str


class UserOut(BaseModel):
    id: str
    name: str
    phone: str | None = None
    email: str | None = None
    role: Role
    customer_id: str | None
    primary_vehicle_id: str | None
    created_at: str
    state: str = "active"
    workshop_id: str | None = None
    registration_workshop_id: str | None = None
    web_position: str | None = None
    web_cargo: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenValidate(BaseModel):
    access_token: str
