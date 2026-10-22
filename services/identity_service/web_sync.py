"""Owner-managed workshop personnel with SQL credentials and rollback records."""
import json
import re
import sqlite3
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from services.common.database import connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.sync_contracts import Configuration, InternalOperation, parse
from services.identity_service.security import hash_password

def init_schema(db):
    columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
    for name in ('web_position', 'web_cargo'):
        if name not in columns:
            db.execute(f'ALTER TABLE users ADD COLUMN {name} TEXT')
    db.execute('CREATE TABLE IF NOT EXISTS web_staff_rollback (id TEXT PRIMARY KEY, workshop_id TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at TEXT NOT NULL)')

def create_router(db_path):
    router = APIRouter(prefix='/internal/web/sync', dependencies=[Depends(require_service_token)])

    @router.get('/staff/{workshop_id}')
    def staff(workshop_id: str):
        with connect(db_path()) as db:
            rows = db.execute("SELECT * FROM users WHERE workshop_id=? AND state != 'provisioning'", (workshop_id,)).fetchall()
        return [{k: v for k, v in dict(row).items() if k != 'password_hash'} for row in rows]

    @router.post('/staff')
    def save(payload: InternalOperation):
        actor, data = payload.actor, payload.data
        workshop_id = actor.get('workshop_id')
        if not workshop_id or actor.get('role') not in ('staff', 'admin') or actor.get('web_cargo') == 'personal_taller':
            raise HTTPException(403, 'Solo el encargado puede administrar el personal.')
        config = parse(Configuration, data)
        members = [p for p in config.datos.personal if p.id != actor['id']]
        passwords = config.passwords
        prepared = {}
        for person in members:
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', person.email):
                raise HTTPException(422, f'Ingresa un correo válido para {person.nombre}.')
            password = passwords.get(person.id)
            if password is not None:
                if not 8 <= len(password) <= 128:
                    raise HTTPException(422, 'Las contraseñas del personal deben tener entre 8 y 128 caracteres.')
                prepared[person.id] = hash_password(password)
        if len({p.id for p in members}) != len(members) or len({p.email.lower() for p in members}) != len(members):
            raise HTTPException(422, 'No repitas perfiles o correos del personal.')
        with connect(db_path()) as db:
            db.execute('BEGIN IMMEDIATE')
            old = [dict(row) for row in db.execute('SELECT * FROM users WHERE workshop_id=? AND id != ?', (workshop_id, actor['id']))]
            before = {item['id']: item for item in old}
            # Validate every identity before making any writes.
            for p in members:
                existing = db.execute('SELECT * FROM users WHERE id=? OR lower(email)=?', (p.id, p.email.lower())).fetchall()
                if any(row['id'] != p.id or row['workshop_id'] != workshop_id or row['id'] == actor['id'] or row['role'] != 'staff' for row in existing):
                    raise HTTPException(409, 'Ese perfil o correo pertenece a otra cuenta.')
                if p.id in before and before[p.id]['email'] != p.email.lower():
                    raise HTTPException(422, 'El correo de un perfil existente no se puede cambiar.')
                if p.id not in before and p.id not in prepared:
                    raise HTTPException(422, f'Define una contraseña para {p.nombre}.')
            db.execute("UPDATE users SET state='inactive' WHERE workshop_id=? AND id != ?", (workshop_id, actor['id']))
            try:
                for p in members:
                    if p.id in before:
                        db.execute("UPDATE users SET name=?, state='active', web_position=?, web_cargo='personal_taller', password_hash=COALESCE(?,password_hash) WHERE id=?", (p.nombre, p.puesto, prepared.get(p.id), p.id))
                    else:
                        db.execute("INSERT INTO users (id,name,phone,email,password_hash,role,created_at,state,workshop_id,registration_workshop_id,web_position,web_cargo) VALUES (?,?,NULL,?,?,'staff',?,'active',?,?,?,'personal_taller')", (p.id, p.nombre, p.email.lower(), prepared[p.id], utc_now_iso(), workshop_id, workshop_id, p.puesto))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, 'Ya existe una cuenta con ese correo.') from error
            after = [dict(row) for row in db.execute('SELECT * FROM users WHERE workshop_id=? AND id != ?', (workshop_id, actor['id']))]
            token = str(uuid4())
            db.execute('INSERT INTO web_staff_rollback VALUES (?,?,?,?,?)', (token, workshop_id, json.dumps(old), json.dumps(after), utc_now_iso()))
            return {'rollbackToken': token}

    @router.post('/staff/{token}/{action}')
    def finish(token: str, action: str):
        with connect(db_path()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM web_staff_rollback WHERE id=?', (token,)).fetchone()
            if not row:
                return {'success': True}
            if action == 'rollback':
                before = {p['id']: p for p in json.loads(row['before_json'])}
                after = json.loads(row['after_json'])
                for saved in after:
                    current = db.execute('SELECT * FROM users WHERE id=?', (saved['id'],)).fetchone()
                    if current is None or dict(current) != saved:
                        raise HTTPException(409, 'El personal cambió desde esta operación; requiere revisión.')
                for saved in after:
                    if saved['id'] in before:
                        fields = before[saved['id']]
                        db.execute('UPDATE users SET ' + ','.join(k+'=?' for k in fields if k != 'id') + ' WHERE id=?', [v for k,v in fields.items() if k != 'id'] + [saved['id']])
                    else:
                        db.execute('DELETE FROM users WHERE id=?', (saved['id'],))
            elif action != 'commit':
                raise HTTPException(404, 'Operación no disponible.')
            db.execute('DELETE FROM web_staff_rollback WHERE id=?', (token,))
        return {'success': True}
    return router
