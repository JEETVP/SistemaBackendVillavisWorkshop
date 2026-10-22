"""Render entrypoint: four supervised services, one public gateway, managed PostgreSQL."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def service_database_urls(database_url):
    parsed=urlsplit(database_url)
    if parsed.scheme not in ('postgresql','postgres') or not parsed.hostname:
        raise ValueError('DATABASE_URL must be a PostgreSQL URL.')
    result={}
    for service in ('identity','customers','workshop'):
        query=[(key,value) for key,value in parse_qsl(parsed.query) if key!='options']
        query.append(('options','-csearch_path='+service))
        result[service]=urlunsplit(parsed._replace(query=urlencode(query)))
    return result


def main():
    from services.common.config import app_origin
    import psycopg
    from psycopg import sql
    app_origin()
    for name in ('INTERNAL_SERVICE_TOKEN','BACKEND_PROXY_TOKEN'):
        if len(os.getenv(name,''))<32:
            raise SystemExit(f'Configure {name} with at least 32 characters.')
    base=os.getenv('DATABASE_URL','')
    urls=service_database_urls(base)
    with psycopg.connect(base,autocommit=True,connect_timeout=10) as db:
        for schema in urls:
            db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
    environment=os.environ.copy()
    environment.update({name.upper()+'_DATABASE_URL':url for name,url in urls.items()})
    environment.update({
        'IDENTITY_SERVICE_URL':'http://127.0.0.1:8003',
        'CUSTOMERS_SERVICE_URL':'http://127.0.0.1:8001',
        'WORKSHOP_SERVICE_URL':'http://127.0.0.1:8002',
        'IDENTITY_KEY_STORAGE':'postgresql',
        'RENDER_DEPLOYMENT':'true',
    })
    port=int(os.getenv('PORT','10000'))
    if port in (8001,8002,8003) or not 1<=port<=65535:
        raise SystemExit('PORT conflicts with an internal service.')
    children=[]
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        for service,internal_port in [('identity_service',8003),('customer_service',8001),('workshop_service',8002),('api_gateway',port)]:
            children.append(subprocess.Popen([sys.executable,'-m','uvicorn',f'services.{service}.app:app',
                '--host','0.0.0.0' if service=='api_gateway' else '127.0.0.1',
                '--port',str(internal_port),'--no-proxy-headers'],cwd=ROOT,env=environment))
        while all(child.poll() is None for child in children):
            time.sleep(.25)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        # Drain the gateway before stopping internal writers.
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__=='__main__':
    raise SystemExit(main())
