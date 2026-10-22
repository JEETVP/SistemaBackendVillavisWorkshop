"""Validated contracts for the React client and internal provisioning operations."""
from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class WebModel(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def trim_text(cls, value, info):
        if isinstance(value, str) and info.field_name not in {"password", "passwordConfirm", "token"}:
            return value.strip()
        return value


class Location(WebModel):
    direccion: str = Field(min_length=1, max_length=200)
    ciudad: str = Field(min_length=1, max_length=200)
    estado: str = Field(min_length=1, max_length=200)
    codigoPostal: str = Field(pattern=r"^\d{5}$")
    pais: Literal["México"] = "México"


class WorkshopRegistration(WebModel):
    nombre: str = Field(min_length=1, max_length=120)
    encargadoNombre: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    ubicacion: Location

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("El correo electrónico no es válido")
        return value.lower()


class CustomerRegistration(WebModel):
    model_config = {"extra": "forbid"}
    nombre: str = Field(min_length=1, max_length=120)
    telefono: str
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("telefono")
    @classmethod
    def valid_phone(cls, value):
        return normalize_web_phone(value)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("El correo electrónico no es válido")
        return value.lower()


class InternalCustomerRegistration(CustomerRegistration):
    id: str = Field(min_length=1, max_length=100)


class CustomerProfileProvision(WebModel):
    id: str
    nombre: str
    telefono: str
    email: str


class WebLogin(WebModel):
    type: Literal["cliente", "taller"]
    telefono: str | None = None
    email: str | None = None
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def valid_identifier(self):
        if self.type == "cliente":
            self.telefono = normalize_web_phone(self.telefono or "")
        elif not self.email or len(self.email) > 254:
            raise ValueError("Ingresa el correo electrónico")
        else:
            self.email = self.email.lower()
        return self


def normalize_web_phone(value: str) -> str:
    phone = re.sub(r"[\s()\-]", "", value)
    if not re.fullmatch(r"[0-9]{10}", phone):
        raise ValueError("Ingresa un teléfono de 10 dígitos")
    return phone


class WebVehicle(WebModel):
    marca: str = Field(min_length=1, max_length=80)
    modelo: str = Field(min_length=1, max_length=80)
    anio: int = Field(strict=True, ge=1900)
    placas: str = Field(default="", max_length=24)
    numeroSerie: str
    cilindros: Literal[0, 3, 4, 6, 8]
    combustible: Literal["Gasolina", "Diésel", "Híbrido", "Eléctrico"]
    kilometraje: int = Field(strict=True, ge=0, le=10_000_000)
    color: str = Field(default="", max_length=50)
    foto: str | None = Field(default=None, max_length=1_400_000)

    @field_validator("anio")
    @classmethod
    def valid_year(cls, value):
        if value > datetime.now().year + 1:
            raise ValueError("Ingresa un año válido")
        return value

    @field_validator("placas")
    @classmethod
    def normalize_plate(cls, value):
        value = re.sub(r"[\s-]", "", value.upper())
        if value and not re.fullmatch(r"[A-Z0-9]{3,12}", value):
            raise ValueError("Ingresa placas válidas")
        return value

    @field_validator("numeroSerie")
    @classmethod
    def valid_vin(cls, value):
        value = value.upper()
        if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", value):
            raise ValueError("El VIN debe contener 17 caracteres válidos")
        return value

    @field_validator("foto")
    @classmethod
    def valid_photo(cls, value):
        if value and not re.fullmatch(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}", value):
            raise ValueError("Selecciona una foto JPG, PNG o WebP válida")
        return value

    @model_validator(mode="after")
    def valid_cylinders(self):
        if (self.combustible == "Eléctrico") != (self.cilindros == 0):
            raise ValueError("Selecciona 3, 4, 6 u 8 cilindros; los eléctricos tienen 0")
        return self


class CustomerIntake(WebModel):
    nombre: str = Field(min_length=1, max_length=120)
    telefono: str
    motivoServicio: str = Field(min_length=1, max_length=1000)
    vehiculo: WebVehicle

    @field_validator("telefono")
    @classmethod
    def valid_phone(cls, value):
        return normalize_web_phone(value)


class ActivationToken(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class ActivationComplete(ActivationToken):
    password: str = Field(min_length=8, max_length=128)
    passwordConfirm: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.passwordConfirm:
            raise ValueError("Las contraseñas no coinciden")
        return self


class ActivationRenew(BaseModel):
    userId: str = Field(min_length=1, max_length=100)


class AccountProvision(WebModel):
    id: str
    role: Literal["client", "staff"]
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None
    email: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    workshop_id: str
    vehicle_id: str | None = None


class WorkshopProvision(BaseModel):
    id: str
    owner_id: str
    nombre: str
    ubicacion: Location


class CustomerProvision(BaseModel):
    id: str
    vehicle_id: str
    actor_id: str
    workshop_id: str
    intake: CustomerIntake


class OrderProvision(BaseModel):
    id: str
    customer_id: str
    vehicle_id: str
    workshop_id: str
    description: str


class AccountLookup(BaseModel):
    customer_ids: list[str] = Field(default_factory=list, max_length=1000)


class VehicleLookup(BaseModel):
    customer_id: str | None = None
    vehicle_ids: list[str] = Field(default_factory=list, max_length=1000)


class InternalRenew(BaseModel):
    user_id: str
    workshop_id: str
