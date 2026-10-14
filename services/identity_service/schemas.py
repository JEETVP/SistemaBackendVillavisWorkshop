from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    client = "client"
    staff = "staff"
    admin = "admin"


class StaffLogin(BaseModel):
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


class StaffUserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.staff


class VehicleSessionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    customer_id: str
    primary_vehicle_id: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str | None = None
    role: Role
    customer_id: str | None
    primary_vehicle_id: str | None
    created_at: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenValidate(BaseModel):
    access_token: str
