"""Convert canonical records to the existing React types without duplicating data."""
import json


def details(record, field="web_details"):
    value = record.get(field) or {}
    return json.loads(value) if isinstance(value, str) else value


def web_user(user):
    result = {"uid": user["id"], "nombre": user["name"], "email": user.get("email") or "",
        "celular": user.get("phone") or "", "role": "user" if user["role"] == "client" else "taller",
        "estado": {"active": "activo", "pending_activation": "pendiente_activacion",
                   "inactive": "inactivo"}.get(user.get("state"), "inactivo"),
        "faltas": 0, "createdAt": user["created_at"], "authSource": "backend"}
    if user.get("workshop_id"):
        result.update(tallerId=user["workshop_id"], cargo=user.get("web_cargo") or "personal_administrativo", puesto=user.get("web_position"))
    return result


def web_workshop(workshop):
    location = details(workshop, "location_json") or {"direccion": workshop["address"], "ciudad": "",
        "estado": "", "codigoPostal": "", "pais": "México"}
    return {"id": workshop["id"], "nombre": workshop["name"], "encargadoId": workshop.get("owner_id") or "",
        "ubicacion": location, "verificacionUbicacion": "pendiente_backend", "createdAt": workshop["created_at"]}


def web_vehicle(vehicle, owner_id):
    extra = details(vehicle)
    return {**extra, "id": vehicle["id"], "conductorId": owner_id, "marca": vehicle["brand"],
        "modelo": vehicle["model"], "anio": vehicle["year"], "placas": vehicle.get("plate") or "",
        "numeroSerie": vehicle.get("vin") or "", "color": vehicle.get("color") or "",
        "cilindros": extra.get("cilindros", 4), "combustible": extra.get("combustible", "Gasolina"),
        "kilometraje": extra.get("kilometraje", 0), "registradoPor": extra.get("registradoPor", owner_id),
        "createdAt": vehicle["created_at"]}


def initial_progress(now):
    stages = ["Diagnóstico", "Cotización", "Autorización", "Servicio", "Entrega"]
    return {"etapa": stages[0], "tecnico": "Por asignar", "actualizado": now, "entregaEstimada": "",
        "etapas": [{"titulo": "Revisamos tu auto" if stage == stages[0] else stage,
            "descripcion": "El taller revisará tu auto para identificar el trabajo necesario."
                if stage == stages[0] else f"Seguimiento de {stage.lower()}.",
            "tareas": [{"nombre": f"Completar {stage.lower()}", "completada": False}]} for stage in stages]}


def web_order(order, owner_id, workshop_name):
    extra = details(order)
    progress = extra.get("progreso") or initial_progress(order["updated_at"])
    stage = {"received": "Diagnóstico", "diagnosis": "Diagnóstico", "awaiting_approval": "Autorización",
             "approved": "Servicio", "in_progress": "Servicio", "ready": "Entrega", "delivered": "Entrega"}
    # Preserve a migrated quotation stage; other canonical status changes remain visible.
    progress = {**progress, "etapa": "Cotización" if progress.get("etapa") == "Cotización" and order["status"] == "diagnosis"
        else stage.get(order["status"], progress["etapa"]), "actualizado": order["updated_at"]}
    state = {"delivered": "Finalizada", "cancelled": "Cancelada", "ready": "Entrega",
             "in_progress": "Devolucion", "approved": "Devolucion"}.get(order["status"], "Revision")
    return {**{key: value for key, value in extra.items() if key != "web_intake"},
        "id": order["id"], "userId": owner_id, "vehiculoId": order["vehicle_id"], "tallerId": order["workshop_id"],
        "tallerNombre": workshop_name, "motivoServicio": order["description"], "estado": state,
        "materiales": extra.get("materiales", []), "servicios": extra.get("servicios", []),
        "fechaInicio": extra.get("fechaInicio", order["created_at"]), "fechaFin": extra.get("fechaFin"),
        "createdAt": order["created_at"], "updatedAt": order["updated_at"], "progreso": progress}
