"""Validated contracts for browser writes persisted by the SQL services."""
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError
from fastapi import HTTPException
from services.common.web_schemas import WebModel

def parse(model, data):
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise HTTPException(422, error.errors()[0]['msg']) from error

class Variant(WebModel):
    id: str = Field(min_length=1, max_length=100)
    nombre: str = Field(min_length=1, max_length=120)
    cilindros: Literal[3, 4, 6, 8] | None = None
    precioCentavos: int = Field(strict=True, ge=0, le=999_999_999)

class CatalogService(WebModel):
    id: str = Field(min_length=1, max_length=100)
    tallerId: str
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str = Field(max_length=1000)
    disponible: bool
    moneda: Literal['MXN']
    prioridad: Literal['Alta', 'Media', 'Baja'] | None = None
    variantes: list[Variant] = Field(min_length=1, max_length=30)
    precioCentavos: int | None = None

    @model_validator(mode='after')
    def unique_variants(self):
        if len({v.id for v in self.variantes}) != len(self.variantes) or len({v.nombre.lower() for v in self.variantes}) != len(self.variantes):
            raise ValueError('Las variantes deben ser únicas.')
        self.precioCentavos = min(v.precioCentavos for v in self.variantes)
        return self

class QuoteService(WebModel):
    servicioId: str = Field(min_length=1, max_length=100)
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str = Field(max_length=1000)
    varianteId: str = Field(min_length=1, max_length=100)
    varianteNombre: str = Field(min_length=1, max_length=120)
    precioCentavos: int = Field(strict=True, ge=0, le=999_999_999)
    prioridad: Literal['Alta', 'Media', 'Baja'] | None = None

def transfer(value):
    if not isinstance(value, str) or (value.strip() and not re.fullmatch(r'[0-9 -]{4,34}', value.strip())):
        raise HTTPException(422, 'Ingresa un número de transferencia válido.')
    return value.strip()

class Person(WebModel):
    id: str = Field(min_length=1, max_length=100)
    nombre: str = Field(max_length=120)
    puesto: Literal['Personal administrativo', 'Mecánico', 'Recepción', 'Técnico', 'Otro']
    especialidad: str = Field(default='', max_length=300)
    email: str = Field(default='', max_length=254)

class Hours(WebModel):
    dias: list[Literal['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']]
    apertura: str
    cierre: str

class Specifications(WebModel):
    descripcion: str = Field(max_length=2000)
    telefono: str = Field(max_length=20)
    foto: str = Field(max_length=1_400_000)
    personal: list[Person] = Field(max_length=100)
    servicios: list[str] = Field(max_length=500)
    puestosTrabajo: int = Field(strict=True, ge=1, le=100)
    vehiculosPorDia: int = Field(strict=True, ge=1, le=1000)
    equipamiento: str = Field(max_length=2000)
    horario: Hours

    def check_complete(self):
        if not self.descripcion or not re.fullmatch(r'[0-9]{10}', self.telefono):
            raise HTTPException(422, 'Completa la descripción y teléfono del taller.')
        if not re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}', self.foto):
            raise HTTPException(422, 'Selecciona una foto válida del taller.')
        if not self.personal or any(not p.nombre for p in self.personal) or len({p.id for p in self.personal}) != len(self.personal):
            raise HTTPException(422, 'Completa el personal sin repetir perfiles.')
        if not self.horario.dias or not all(re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]', h) for h in (self.horario.apertura, self.horario.cierre)) or self.horario.apertura >= self.horario.cierre:
            raise HTTPException(422, 'Revisa los días y el horario de atención.')

class Configuration(WebModel):
    datos: Specifications
    complete: bool
    passwords: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_complete(self):
        if self.complete:
            self.datos.check_complete()
        return self

class InternalOperation(BaseModel):
    actor: dict
    data: dict = Field(default_factory=dict)

class Mileage(BaseModel):
    kilometros: int = Field(strict=True, gt=0, le=10_000_000)
    operationId: str = Field(min_length=1, max_length=100)

class Fuel(BaseModel):
    kilometraje: int = Field(strict=True, ge=0, le=10_000_000)
    litros: float = Field(gt=0, le=1000, allow_inf_nan=False)
    tanqueLleno: bool
    operationId: str = Field(min_length=1, max_length=100)
