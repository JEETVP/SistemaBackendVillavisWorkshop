"""Point an existing TallerPlusWEB checkout at FastAPI while preserving its changes."""
import argparse
from pathlib import Path


VITE_CONFIG = '''import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = process.env.FASTAPI_URL || env.FASTAPI_URL || 'http://127.0.0.1:8000'
  const proxy = { '/api': { target, changeOrigin: false } }
  return {
    plugins: [react(), tailwindcss()],
    server: { proxy },
    preview: { proxy },
    resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  }
})
'''

DEV_SCRIPT = '''import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

if (existsSync('.env')) process.loadEnvFile('.env');
const port = process.env.VITE_PORT || '5173';
console.log('Taller+ usa FastAPI en ' + (process.env.FASTAPI_URL || 'http://127.0.0.1:8000'));
console.log('Inicia el backend con .venv/Scripts/python.exe scripts/dev.py desde su proyecto.');
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--port', port, '--strictPort'], {
  stdio: 'inherit', windowsHide: true, env: process.env,
});
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code) => { process.exitCode = code ?? 0; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill());
'''

ENV = '''# Development proxy. Server-side only; do not prefix backend secrets with VITE_.
FASTAPI_URL=http://127.0.0.1:8000
VITE_PORT=5173
'''

LOGIN = '''  const login = async (identifier: string, password: string, type: 'cliente' | 'taller' = 'cliente') => {
    authVersion.current++;
    setLoading(true); setError('');
    try {
      const data = type === 'cliente' ? await customerLogin(identifier, password) : await workshopLogin(identifier, password);
      cacheSession(data);
      const foundUser = data.user;
      setStorageData('current_user', foundUser);
      setUser(foundUser); setUserRole(foundUser.role); setUsers(getRegisteredUsers());
      window.dispatchEvent(new Event('tallerplus_auth_changed'));
      return { success: true as const, user: foundUser };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error al iniciar sesión';
      setError(message); return { success: false as const, error: message };
    } finally { setLoading(false); }
  };

'''

DOC = '''# Migración a FastAPI: primera fase

La web consume `/api` desde el mismo origen y Vite lo redirige a FastAPI. `npm run dev` inicia únicamente Vite; ya no inicia la API Node ni crea cuentas demo. Se conserva `server/` para consultar el comportamiento anterior y sus pruebas; no es el servidor activo de la aplicación.

1. En SistemaBackendVillavisWorkshop, instalar sus dependencias y configurar `.env` a partir de `.env.example`. Ejecutar `.\\.venv\\Scripts\\python.exe scripts/dev.py` (Linux/macOS: `.venv/bin/python scripts/dev.py`).
2. En TallerPlusWEB, configurar `.env` con `FASTAPI_URL=http://127.0.0.1:8000` y `VITE_PORT=5173`; ejecutar `npm run dev` (PowerShell: `npm.cmd run dev`).
3. Abrir `http://localhost:5173`. `APP_ORIGIN` del backend debe coincidir exactamente con ese origen; la cookie requiere el proxy del mismo origen. Para producción, servir `dist`, redirigir `/api` al gateway y configurar `APP_ORIGIN` con el dominio HTTPS.

Están migrados registro de taller/encargado, login de taller por correo y cliente por teléfono, sesión HttpOnly, logout, recepción, activación y renovación, y directorio de talleres. Se usan las bases canónicas de identidad, clientes y taller de FastAPI. Los tokens quedan en cookies HttpOnly; el frontend no recibe JWT en JSON.

Los registros del SQLite de Node se importan desde el backend con `scripts/migrate_node_sqlite.py`: primero vista previa y luego `--apply`, con servicios detenidos. La fuente se abre en modo de solo lectura; se respaldan destinos existentes, se conservan IDs, credenciales scrypt y enlaces pendientes. Las sesiones anteriores requieren iniciar sesión de nuevo. Los datos que solo existen en localStorage no se importan con ese comando.

El acceso y la restauración de sesión siempre se validan con FastAPI; las contraseñas y perfiles locales antiguos no habilitan una sesión. Las cuentas antiguas que solo existían en el navegador requieren una migración posterior o un alta en el servidor.

La configuración, catálogo, personal, solicitudes posteriores a la recepción, edición de cotizaciones, avances, fotos adicionales, kilometraje, combustible y favoritos todavía usan sus adaptadores locales. Esta primera fase no convierte esas escrituras en operaciones sincronizadas. Las pruebas de `server/` verifican el contrato anterior; las nuevas pruebas de FastAPI están en el proyecto del backend.

La configuración pública del frontend no debe contener claves internas, contraseñas ni claves privadas del backend.
'''


def update(frontend):
    root = frontend.resolve()
    if not (root / 'src/services/customerApi.ts').is_file() or not (root / 'server/database.mjs').is_file():
        raise ValueError('The target is not a TallerPlusWEB checkout')
    changes = []
    def write(relative, value):
        destination = (root / relative).resolve()
        if not destination.is_relative_to(root):
            raise ValueError('Frontend path escaped the checkout')
        if destination.exists() and destination.read_text(encoding='utf-8') == value:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(value, encoding='utf-8')
        changes.append(relative)

    write('vite.config.ts', VITE_CONFIG)
    write('scripts/dev.mjs', DEV_SCRIPT)
    write('.env.example', ENV)
    if not (root / '.env').exists():
        write('.env', ENV)
    ignored = (root / '.gitignore').read_text(encoding='utf-8')
    if '\n.env\n' not in '\n' + ignored:
        write('.gitignore', ignored.rstrip() + '\n\n# Local environment files\n.env\n.env.*\n!.env.example\n')
    write('docs/migracion-fastapi.md', DOC)
    readme = (root / 'README.md').read_text(encoding='utf-8')
    banner = '> El servidor activo ahora es FastAPI. Inicia el backend por separado y consulta [Migración a FastAPI](docs/migracion-fastapi.md). `npm run dev` inicia solo la web.\n\n'
    if banner not in readme:
        readme = readme.replace('# Taller+\n\n', '# Taller+\n\n' + banner, 1)
    readme = readme.replace('para iniciar la web y la API local.', 'para iniciar la web. El backend FastAPI se inicia por separado.')
    write('README.md', readme)
    activation_doc = root / 'docs/activacion-clientes.md'
    historical = '> Actualización: la API activa se migró a FastAPI. Consulta [Migración a FastAPI](migracion-fastapi.md); las referencias a Node, scrypt y al arranque conjunto de este documento describen la implementación anterior.\n\n'
    if activation_doc.exists():
        text = activation_doc.read_text(encoding='utf-8')
        if historical not in text:
            write('docs/activacion-clientes.md', historical + text)
    auth = (root / 'src/hooks/useAuth.tsx').read_text(encoding='utf-8')
    auth = auth.replace("import { getRegisteredUsers, verifyTallerPassword }", "import { getRegisteredUsers }")
    auth = auth.replace("import { ensureDemoServiceData } from '../mock/serviceDemo';\n", '')
    auth = auth.replace("import { getConductorAccounts } from '../services/conductorStore';\n", '')
    auth = auth.replace("import { verifyConductorPassword } from '../services/conductorRegistration';\n", '')
    auth = auth.replace('getStorageData, setStorageData, INITIAL_SOLICITUDES, INITIAL_USERS', 'getStorageData, setStorageData')
    initial_start = auth.index('  const [users, setUsers]')
    initial_end = auth.index('  const [user, setUser]', initial_start)
    auth = auth[:initial_start] + '''  const [users, setUsers] = useState<User[]>(() => {
    cleanupLegacyDemo();
    return getRegisteredUsers();
  });
''' + auth[initial_end:]
    loading_start = auth.index('  const [loading, setLoading]')
    loading_end = auth.index('\n\n', loading_start)
    auth = auth[:loading_start] + '  const [loading, setLoading] = useState<boolean>(true);' + auth[loading_end:]
    auth = auth.replace("    const cached = getStorageData<User | null>('current_user', null);\n    if (cached && cached.authSource !== 'backend') return;\n", '')
    login_start = auth.index('  const login = async')
    login_end = auth.index('  const logout = async', login_start)
    auth = auth[:login_start] + LOGIN + auth[login_end:]
    auth = auth.replace("if (user?.authSource === 'backend') await endSession();", 'await endSession();')
    write('src/hooks/useAuth.tsx', auth)
    package = (root / 'package.json').read_text(encoding='utf-8')
    old = '"server": "node server/index.mjs",'
    new = '"server:legacy": "node server/index.mjs",'
    if old in package:
        write('package.json', package.replace(old, new, 1))
    elif new not in package:
        raise ValueError('Unexpected server script; inspect package.json before changing it')
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend', type=Path, required=True)
    args = parser.parse_args()
    for name in update(args.frontend):
        print(f'Updated {name}')
