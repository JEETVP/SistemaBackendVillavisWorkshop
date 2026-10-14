from __future__ import annotations

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=5, max_length=40)
    email: str | None = Field(default=None, max_length=120)


class CustomerOut(CustomerCreate):
    id: str
    created_at: str


class VehicleCreate(BaseModel):
    plate: str = Field(min_length=3, max_length=20)
    vin: str = Field(min_length=5, max_length=17)
    brand: str = Field(min_length=2, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vehicle_type: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    engine_number: str | None = Field(default=None, max_length=80)
    service_type: str | None = Field(default=None, max_length=60)
    owner_name: str | None = Field(default=None, max_length=120)


class VehicleOut(VehicleCreate):
    id: str
    customer_id: str
    created_at: str


class VehicleUpdate(BaseModel):
    plate: str | None = Field(default=None, min_length=3, max_length=20)
    vin: str | None = Field(default=None, min_length=5, max_length=40)
    brand: str | None = Field(default=None, min_length=2, max_length=60)
    model: str | None = Field(default=None, min_length=1, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vehicle_type: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    engine_number: str | None = Field(default=None, max_length=80)
    service_type: str | None = Field(default=None, max_length=60)
    owner_name: str | None = Field(default=None, max_length=120)
