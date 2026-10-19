from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=5, max_length=40)
    email: str | None = Field(default=None, max_length=120)


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


class VehicleAccountRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)
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


class StaffLogin(BaseModel):
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)


class StaffUserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=24, pattern=r"^[+0-9()\-\s]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="staff", pattern="^(staff|admin)$")


class WorkshopCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=5, max_length=240)
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    active: bool = True


class WorkshopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = Field(default=None, min_length=5, max_length=240)
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None


class ServiceCreate(BaseModel):
    workshop_id: str
    name: str = Field(min_length=3, max_length=120)
    service_type: str = Field(min_length=3, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    priority_rank: int = Field(default=2, ge=1, le=3)
    price_3_cyl: float = Field(ge=0)
    price_4_cyl: float = Field(ge=0)
    price_6_cyl: float = Field(ge=0)
    price_8_cyl: float = Field(ge=0)
    parts_brand: str | None = Field(default=None, max_length=240)
    supplies_brand: str | None = Field(default=None, max_length=240)
    base_price: float | None = Field(default=None, ge=0)
    estimated_minutes: int | None = Field(default=None, ge=1)
    active: bool = True


class ServiceUpdate(BaseModel):
    workshop_id: str | None = None
    name: str | None = Field(default=None, min_length=3, max_length=120)
    service_type: str | None = Field(default=None, min_length=3, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    priority_rank: int | None = Field(default=None, ge=1, le=3)
    price_3_cyl: float | None = Field(default=None, ge=0)
    price_4_cyl: float | None = Field(default=None, ge=0)
    price_6_cyl: float | None = Field(default=None, ge=0)
    price_8_cyl: float | None = Field(default=None, ge=0)
    parts_brand: str | None = Field(default=None, max_length=240)
    supplies_brand: str | None = Field(default=None, max_length=240)
    base_price: float | None = Field(default=None, ge=0)
    estimated_minutes: int | None = Field(default=None, ge=1)
    active: bool | None = None


class AppointmentCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    intake_id: str | None = None
    requested_at: str
    notes: str | None = Field(default=None, max_length=500)
    services: list["AppointmentServiceCreate"] = Field(default_factory=list)


class AppointmentServiceCreate(BaseModel):
    service_id: str
    cylinder_count: Literal[3, 4, 6, 8]
    quantity: int = Field(default=1, ge=1)


class VehicleIntakeCreate(BaseModel):
    workshop_id: str
    vehicle_id: str
    vin: str = Field(min_length=5, max_length=17)
    has_tapones: bool = False
    has_virlos: bool = False
    has_tapa_gasolina: bool = False
    has_rines: bool = False
    has_ceniceros: bool = False
    has_llanta_refaccion: bool = False
    detail_notes: str | None = Field(default=None, max_length=1000)
    photo_urls: list[str] = Field(default_factory=list)


class ServiceCartCreate(BaseModel):
    workshop_id: str
    vehicle_id: str
    intake_id: str | None = None


class ServiceCartItemCreate(BaseModel):
    service_id: str
    cylinder_count: Literal[3, 4, 6, 8]
    quantity: int = Field(default=1, ge=1)


class ServiceCartItemUpdate(BaseModel):
    cylinder_count: Literal[3, 4, 6, 8] | None = None
    quantity: int | None = Field(default=None, ge=1)


class ServiceCartCheckoutCreate(BaseModel):
    requested_at: str
    deposit_percentage: Literal[30, 50]
    notes: str | None = Field(default=None, max_length=500)


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(requested|confirmed|cancelled|completed)$")


class WorkOrderCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    description: str = Field(min_length=5, max_length=500)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    appointment_id: str | None = None


class WorkOrderStatusUpdate(BaseModel):
    status: str = Field(
        pattern="^(received|diagnosis|awaiting_approval|approved|in_progress|ready|delivered|cancelled)$"
    )


class TaskStatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|done)$")


class TaskCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    price: float = Field(default=0, ge=0)
    service_id: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class QuoteItemCreate(BaseModel):
    description: str = Field(min_length=3, max_length=180)
    quantity: int = Field(default=1, ge=1)
    unit_price: float = Field(default=0, ge=0)
    service_id: str | None = None
    cylinder_count: Literal[3, 4, 6, 8] | None = None


class QuoteCreate(BaseModel):
    work_order_id: str
    notes: str | None = Field(default=None, max_length=500)
    items: list[QuoteItemCreate] = Field(default_factory=list)


class QuoteStatusUpdate(BaseModel):
    status: str = Field(pattern="^(draft|sent|accepted|rejected)$")


class EvidenceCreate(BaseModel):
    file_url: str = Field(min_length=5, max_length=500)
    caption: str | None = Field(default=None, max_length=240)


class RecommendationCreate(BaseModel):
    vehicle_id: str
    title: str = Field(min_length=3, max_length=160)
    notes: str | None = Field(default=None, max_length=500)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    due_date: str | None = None


class PaymentCreate(BaseModel):
    work_order_id: str
    amount: float = Field(gt=0)
    provider: str = Field(default="manual", max_length=40)
    reference: str | None = Field(default=None, max_length=120)
    status: str = Field(default="registered", pattern="^(pending|registered|paid|failed)$")
