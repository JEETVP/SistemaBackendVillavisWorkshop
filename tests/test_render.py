import os
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from test_integration import ServiceFixture
from services.identity_service import app as identity
from services.common import security
from services.common.database import close_pool
from scripts.render_start import service_database_urls


class RenderDeploymentTests(ServiceFixture):
    def test_signing_key_survives_pool_and_process_style_reconnects(self):
        with patch.dict(os.environ,{'IDENTITY_DATABASE_URL':identity.DATABASE_URL}):
            first=security.postgres_private_key()
            security._postgres_keys.pop(identity.DATABASE_URL, None)
            close_pool(identity.DATABASE_URL)
            second=security.postgres_private_key()
            self.assertEqual(first,second)
            self.assertIn(b'BEGIN PRIVATE KEY',first)

    def test_cloudflare_proxy_is_authenticated_without_weakening_origin_check(self):
        secret='a'*64
        with patch.dict(os.environ,{'RENDER_DEPLOYMENT':'true','BACKEND_PROXY_TOKEN':secret}):
            self.assertEqual(self.client.get('/api/health').status_code,403)
            self.assertEqual(self.client.get('/api/health',headers={'X-Frontend-Token':secret}).status_code,200)
            self.assertEqual(self.client.get('/auth/me',headers={'X-Frontend-Token':secret}).status_code,404)
            self.assertEqual(self.client.get('/health').status_code,200)
            forbidden=self.client.post('/api/auth/login',headers={'X-Frontend-Token':secret,'Origin':'https://evil.example'},json={'type':'cliente','telefono':'0000000000','password':'Testing123!'})
            self.assertEqual(forbidden.status_code,403)

    def test_render_uses_three_schemas_and_preserves_postgres_tls_options(self):
        urls=service_database_urls('postgresql://user:password@database/tallerplus?sslmode=require')
        self.assertEqual(set(urls),{'identity','customers','workshop'})
        for schema,url in urls.items():
            parsed=urlsplit(url)
            self.assertEqual(parsed.path,'/tallerplus')
            self.assertEqual(parse_qs(parsed.query),{'sslmode':['require'],'options':['-csearch_path='+schema]})
