"""CI smoke test of the actual Render container over loopback HTTP."""
import os
import time
import httpx

base='http://127.0.0.1:10000'
secret=os.environ['SMOKE_PROXY_TOKEN']
origin='https://tallerplus.pages.dev'
with httpx.Client(base_url=base,timeout=15,trust_env=False) as client:
    for attempt in range(60):
        try:
            health=client.get('/health')
            if health.status_code==200 and health.json()['status']=='ok':
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit('Render container did not become healthy.')
    assert client.get('/api/auth/session').status_code==403
    client.headers.update({'X-Frontend-Token':secret,'Origin':origin,'X-Frontend-Client-IP':'203.0.113.42'})
    account=client.post('/api/auth/customers',json={'nombre':'CI Render','telefono':'2226543210','email':'render-ci@example.test','password':'PruebaRender123!'})
    assert account.status_code==201, account.text
    cookie=account.headers['set-cookie']
    assert 'httponly' in cookie.lower() and 'secure' in cookie.lower()
    client.headers['Cookie']='tallerplus_session='+account.cookies['tallerplus_session']
    session=client.get('/api/auth/session')
    assert session.status_code==200
    assert session.json()['user']['uid']==account.json()['user']['uid']
    denied=client.post('/api/auth/login',headers={'Origin':'https://foreign.example'},json={'type':'cliente','telefono':'2226543210','password':'PruebaRender123!'})
    assert denied.status_code==403
print('Render-style startup, PostgreSQL and proxied session passed.')
