from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Priority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class WorkOrderStatus(str, Enum):
    received = "received"
    diagnosis = "diagnosis"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    in_progress = "in_progress"
    ready = "ready"
    delivered = "delivered"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"


class AppointmentStatus(str, Enum):
    requested = "requested"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"


class PaymentStatus(str, Enum):
    pending = "pending"
    registered = "registered"
    paid = "paid"
    failed = "failed"


class DepositPercentage(int, Enum):
    thirty = 30
    fifty = 50


class WorkshopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=5, max_length=240)
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    active: bool = True


class WorkshopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, min_length=5, max_length=240)
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None


class WorkshopOut(WorkshopCreate):
    id: str
    created_at: str


class CylinderCount(int, Enum):
    three = 3
    four = 4
    six = 6
    eight = 8


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


class ServiceOut(ServiceCreate):
    id: str
    created_at: str


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


class ServicePriceOut(BaseModel):
    service_id: str
    workshop_id: str
    name: str
    service_type: str
    priority_rank: int
    cylinder_count: CylinderCount
    unit_price: float
    parts_brand: str | None
    supplies_brand: str | None


class ServiceCartCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    intake_id: str | None = None


class ServiceCartItemCreate(BaseModel):
    service_id: str
    cylinder_count: CylinderCount
    quantity: int = Field(default=1, ge=1)


class ServiceCartItemUpdate(BaseModel):
    cylinder_count: CylinderCount | None = None
    quantity: int | None = Field(default=None, ge=1)


class ServiceCartItemOut(BaseModel):
    id: str
    cart_id: str
    service_id: str
    service_name: str
    service_type: str
    priority_rank: int
    cylinder_count: int
    quantity: int
    unit_price: float
    line_total: float


class ServiceCartPrioritySummary(BaseModel):
    priority_rank: int
    item_count: int
    total: float


class ServiceCartOut(ServiceCartCreate):
    id: str
    status: str
    subtotal: float
    created_at: str
    updated_at: str
    items: list[ServiceCartItemOut] = Field(default_factory=list)
    priority_summary: list[ServiceCartPrioritySummary] = Field(default_factory=list)


class ServiceCartCheckoutCreate(BaseModel):
    requested_at: str = Field(description="ISO 8601 date/time requested by the client")
    deposit_percentage: DepositPercentage
    notes: str | None = Field(default=None, max_length=500)


class AppointmentServiceCreate(BaseModel):
    service_id: str
    cylinder_count: CylinderCount
    quantity: int = Field(default=1, ge=1)


class AppointmentServiceOut(AppointmentServiceCreate):
    id: str
    appointment_id: str
    service_name: str
    unit_price: float
    estimated_total: float


class VehicleIntakeCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    has_tapones: bool = False
    has_virlos: bool = False
    has_tapa_gasolina: bool = False
    has_rines: bool = False
    has_ceniceros: bool = False
    has_llanta_refaccion: bool = False
    detail_notes: str | None = Field(default=None, max_length=1000)
    photo_urls: list[str] = Field(default_factory=list)


class VehicleIntakePhotoOut(BaseModel):
    id: str
    intake_id: str
    photo_url: str
    created_at: str


class VehicleIntakeOut(VehicleIntakeCreate):
    id: str
    created_at: str
    photos: list[VehicleIntakePhotoOut] = Field(default_factory=list)


class AppointmentCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    intake_id: str | None = None
    requested_at: str = Field(description="ISO 8601 date/time requested by the client")
    notes: str | None = Field(default=None, max_length=500)
    services: list[AppointmentServiceCreate] = Field(default_factory=list)


class AppointmentOut(AppointmentCreate):
    id: str
    status: AppointmentStatus
    estimated_total: float
    created_at: str
    updated_at: str


class AppointmentDetail(AppointmentOut):
    services: list[AppointmentServiceOut]


class PaymentRequestOut(BaseModel):
    id: str
    appointment_id: str
    cart_id: str
    customer_id: str
    vehicle_id: str
    provider: str
    service_total: float
    deposit_percentage: int
    deposit_amount: float
    payment_link: str
    status: PaymentStatus
    created_at: str
    updated_at: str


class PurchaseTicketOut(BaseModel):
    id: str
    ticket_number: str
    appointment_id: str
    payment_request_id: str
    customer_id: str
    vehicle_id: str
    service_total: float
    deposit_percentage: int
    deposit_amount: float
    status: str
    created_at: str


class AppNotificationOut(BaseModel):
    id: str
    customer_id: str
    title: str
    message: str
    notification_type: str
    related_entity_type: str | None
    related_entity_id: str | None
    read_at: str | None
    created_at: str


class WorkshopNotificationOut(BaseModel):
    id: str
    workshop_id: str
    title: str
    message: str
    notification_type: str
    related_entity_type: str | None
    related_entity_id: str | None
    read_at: str | None
    created_at: str


class CartCheckoutOut(BaseModel):
    cart: ServiceCartOut
    appointment: AppointmentDetail
    work_order: "WorkOrderDetail"
    payment_request: PaymentRequestOut
    ticket: PurchaseTicketOut
    notification: AppNotificationOut


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus


class WorkOrderCreate(BaseModel):
    workshop_id: str
    customer_id: str
    vehicle_id: str
    description: str = Field(min_length=1, max_length=1000)
    priority: Priority = Priority.normal
    appointment_id: str | None = None


class WorkOrderOut(WorkOrderCreate):
    id: str
    status: WorkOrderStatus
    estimated_total: float
    created_at: str
    updated_at: str


class WorkOrderStatusUpdate(BaseModel):
    status: WorkOrderStatus


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class TaskCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    price: float = Field(default=0, ge=0)
    service_id: str | None = None
    priority: Priority = Priority.normal


class TaskOut(TaskCreate):
    id: str
    work_order_id: str
    status: TaskStatus
    created_at: str
    updated_at: str | None = None


class QuoteItemCreate(BaseModel):
    description: str = Field(min_length=3, max_length=180)
    quantity: int = Field(default=1, ge=1)
    unit_price: float = Field(default=0, ge=0)
    service_id: str | None = None
    cylinder_count: CylinderCount | None = None


class QuoteItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, min_length=3, max_length=180)
    quantity: int | None = Field(default=None, ge=1)
    unit_price: float | None = Field(default=None, ge=0)

    @field_validator("description", "quantity", "unit_price", mode="before")
    @classmethod
    def supplied_values_cannot_be_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be null")
        return value.strip() if isinstance(value, str) else value


class QuoteCreate(BaseModel):
    work_order_id: str
    notes: str | None = Field(default=None, max_length=500)
    items: list[QuoteItemCreate] = Field(default_factory=list)


class QuoteStatusUpdate(BaseModel):
    status: QuoteStatus


class QuoteItemOut(QuoteItemCreate):
    id: str
    quote_id: str
    total: float


class QuoteOut(BaseModel):
    id: str
    work_order_id: str
    status: QuoteStatus
    subtotal: float
    notes: str | None
    created_at: str
    updated_at: str
    items: list[QuoteItemOut] = Field(default_factory=list)


class EvidenceCreate(BaseModel):
    file_url: str = Field(min_length=5, max_length=500)
    caption: str | None = Field(default=None, max_length=240)


class EvidenceOut(EvidenceCreate):
    id: str
    work_order_id: str
    created_at: str


class RecommendationCreate(BaseModel):
    vehicle_id: str
    title: str = Field(min_length=3, max_length=160)
    notes: str | None = Field(default=None, max_length=500)
    priority: Priority = Priority.normal
    due_date: str | None = None


class RecommendationOut(RecommendationCreate):
    id: str
    status: str
    created_at: str


class PaymentCreate(BaseModel):
    work_order_id: str
    amount: float = Field(gt=0)
    provider: str = Field(default="manual", max_length=40)
    reference: str | None = Field(default=None, max_length=120)
    status: PaymentStatus = PaymentStatus.registered


class PaymentOut(PaymentCreate):
    id: str
    created_at: str


class WorkOrderDetail(WorkOrderOut):
    tasks: list[TaskOut]
    quotes: list[QuoteOut]
    evidence: list[EvidenceOut]
    payments: list[PaymentOut]
    total_tasks: int = 0
    completed_tasks: int = 0
    progress_percent: float = 0


class NotificationCountOut(BaseModel):
    unread_count: int


class NotificationBulkUpdateOut(BaseModel):
    updated_count: int
    unread_count: int


class AdminDashboardOut(BaseModel):
    workshop_id: str | None
    pending_appointments: int
    received_orders: int
    active_orders: int
    ready_orders: int
    unread_workshop_notifications: int
    pending_payment_requests: int
    estimated_open_revenue: float


class ServiceReportOut(BaseModel):
    service_id: str | None
    service_name: str
    service_type: str | None = None
    times_requested: int
    revenue: float


class WorkshopReportOut(BaseModel):
    workshop_id: str | None
    date_from: str | None
    date_to: str | None
    total_appointments: int
    total_orders: int
    completed_orders: int
    cancelled_orders: int
    active_orders: int
    estimated_revenue: float
    paid_amount: float
    pending_deposit_amount: float
    top_services: list[ServiceReportOut] = Field(default_factory=list)
