# ADICLA Sign

Sistema de gestión, distribución interna y firma de documentos PDF para ADICLA.
Está desarrollado con Python, Django 5.2, PostgreSQL, HTML, CSS y JavaScript.
Utiliza Psycopg para la base de datos, PDF.js local para visualizar documentos,
y pypdf y ReportLab para generar el PDF resultante. La entrega operativa es
**local**; el despliegue en cPanel está pendiente.

## Ejecución local (Windows)

### Requisitos e instalación

- Python: se recomienda usar el entorno validado con **3.14.6** para reproducir
  la ejecución local comprobada. `requirements.txt` fija Django **5.2.17** y las
  demás versiones utilizadas; la recomendación de Python 3.12 para cPanel no
  sustituye esta referencia local.
- PostgreSQL 14 o posterior; el entorno local documentado utiliza PostgreSQL 17.
- Acceso a una base y un rol de PostgreSQL propios de la aplicación.

Desde la raíz del proyecto, cree un entorno virtual si aún no existe e instale
las dependencias con ese mismo intérprete (en Windows, con Python 3.14
disponible mediante `py`):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Si `.venv` ya existe, no es necesario recrearlo. Utilice siempre su
`python.exe` en los comandos siguientes.

### PostgreSQL y variables de entorno

PostgreSQL es el motor oficial. La base y el rol deben crearse una sola vez como
administrador de PostgreSQL, **solo si aún no existen**. El rol de la aplicación
debe ser propietario de su base y esquema, sin conservar `SUPERUSER`, `CREATEDB`
ni `CREATEROLE` durante el uso ordinario:

```sql
CREATE ROLE docu_postgres_dev_user LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password docu_postgres_dev_user
CREATE DATABASE docu_postgres_dev OWNER docu_postgres_dev_user ENCODING 'UTF8' TEMPLATE template0;
\connect docu_postgres_dev
ALTER SCHEMA public OWNER TO docu_postgres_dev_user;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO docu_postgres_dev_user;
```

Configure `.env` a partir de `.env.example` para la máquina local. `DB_ENGINE`,
`DB_NAME`, `DB_USER` y `DB_PASSWORD` son obligatorios para PostgreSQL;
`DB_PASSWORD` debe contener la contraseña del rol local, nunca versionada.
`DJANGO_DEBUG=True` habilita el entorno de desarrollo. Use una clave secreta
propia si establece `DJANGO_SECRET_KEY`; con debug desactivado es obligatoria.
El ejemplo incluye los nombres de base y rol utilizados en el procedimiento
anterior; ajústelos si su instalación usa otros:

```dotenv
DB_ENGINE=postgresql
DB_NAME=docu_postgres_dev
DB_USER=docu_postgres_dev_user
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=5432
DB_TEST_NAME=test_docu_postgres_dev
```

`DB_HOST` y `DB_PORT` son opcionales (por defecto `localhost` y `5432`);
`DB_TEST_NAME` debe ser distinto de `DB_NAME`. `DJANGO_ALLOWED_HOSTS` puede
contener `127.0.0.1,localhost` para el acceso local. Las demás variables
opcionales y los ejemplos futuros para cPanel se describen en `.env.example`.
No use sus rutas de hosting para ejecutar localmente.

Antes de migrar o ejecutar pruebas, verifique el destino que reporta el propio
servidor. Sustituya los nombres, host y puerto del comando si modificó el
ejemplo; esta consulta no cambia el esquema:

```powershell
.\.venv\Scripts\python.exe scripts\verify_postgresql_target.py `
  --database docu_postgres_dev `
  --test-database test_docu_postgres_dev `
  --host 127.0.0.1 `
  --port 5432 `
  --require-test-database-absent
```

El comando falla si el backend, vendor, base, host, puerto o nombre de prueba
no son los esperados. Para una base nueva se puede añadir
`--require-empty-schema`; no lo use sobre una base ya migrada.

### Migraciones y primer administrador

Compruebe la configuración y aplique las migraciones **únicamente sobre la
base prevista**, tras verificar el destino. Las migraciones incluyen los cargos
y comités oficiales iniciales:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe scripts\verify_postgresql_target.py `
  --database docu_postgres_dev `
  --test-database test_docu_postgres_dev `
  --inspect-schema
```

Si todavía no existe una cuenta administradora, créela con:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

El modelo de usuario solicita correo institucional, nombre, apellido, comité
y cargo, además de la contraseña. Seleccione un comité y cargo existentes
después de migrar. No comparta ni incluya la contraseña en la documentación.
Para gestores no superusuarios, asigne `is_staff` y los permisos específicos
desde una cuenta administradora autorizada (véase más abajo).

### Iniciar y acceder

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Abra `http://127.0.0.1:8000/` (redirige al acceso o al panel, según la sesión).
El acceso administrativo está en `http://127.0.0.1:8000/admin/` y requiere
`is_staff` y los permisos correspondientes. Detenga el servidor con `Ctrl+C`.

### Pruebas en una base temporal

Django crea y elimina `test_docu_postgres_dev`; nunca utiliza
`docu_postgres_dev` como base de pruebas. El rol de desarrollo recibe
`CREATEDB` **solo temporalmente** durante la ejecución de la suite. Revise
primero que `DB_TEST_NAME` no coincida con `DB_NAME` y que la base de prueba no
exista. Como administrador de PostgreSQL:

```sql
ALTER ROLE docu_postgres_dev_user CREATEDB;
```

Compruebe el privilegio y la ausencia de la base temporal antes de ejecutar:

```powershell
.\.venv\Scripts\python.exe scripts\verify_postgresql_target.py `
  --database docu_postgres_dev `
  --test-database test_docu_postgres_dev `
  --require-test-database-absent `
  --require-createdb
.\.venv\Scripts\python.exe manage.py test --noinput
```

Revoque el privilegio aunque la suite falle y compruebe el estado final:

```sql
ALTER ROLE docu_postgres_dev_user NOCREATEDB;
```

```powershell
.\.venv\Scripts\python.exe scripts\verify_postgresql_target.py `
  --database docu_postgres_dev `
  --test-database test_docu_postgres_dev `
  --require-test-database-absent `
  --require-no-createdb
```

### Archivos estáticos y multimedia

Con `DJANGO_DEBUG=True`, `runserver` sirve los estáticos de `static/`, incluido
PDF.js. Los PDF cargados se almacenan por defecto en `media/` y se consultan a
través de vistas autenticadas; no publique `MEDIA_ROOT` directamente. Las
firmas de perfil se conservan en la base de datos. `STATIC_ROOT` usa
`staticfiles/` por defecto y puede configurarse con `DJANGO_STATIC_ROOT` para
un despliegue posterior. En ese caso, ejecute `collectstatic` y configure el
servidor web para servir el directorio bajo `STATIC_URL`:

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Para una validación aislada, asigne `DJANGO_STATIC_ROOT` a un directorio
temporal vacío; no use como destino una carpeta productiva existente.

### Limitaciones conocidas

- La entrega operativa es local. El enrutamiento de LiteSpeed/Passenger con
  WordPress impide dar por completado el despliegue en cPanel.
- El MVP no verifica el correo ni envía notificaciones reales. La recuperación
  de contraseña y el rechazo de documentos no forman parte del flujo real.
- El registro público permite escoger los cinco cargos, incluidos presidente
  y secretario, con efecto funcional inmediato; consulte el riesgo aceptado
  en la sección de administración.
- La instalación oficial incluye únicamente el backend PostgreSQL. La rama
  histórica `DB_ENGINE=mssql` permanece en `config/settings.py`, pero
  `mssql-django` y `pyodbc` no están en `requirements.txt`.

## Visualización técnica de documentos

Abrir la pantalla de firma, consultar el PDF o descargar un archivo mediante
`GET` no modifica el estado del destinatario. La pantalla de firma registra la
visualización con un `POST` a
`/firma/destinatarios/<id>/visualizacion/` únicamente después de que PDF.js
renderiza correctamente la primera página.

El endpoint exige sesión autenticada y CSRF, comprueba que la asignación
pertenezca al usuario y que el envío continúe activo, y bloquea la fila dentro
de una transacción. Solo la primera solicitud cambia `PENDIENTE` a `VISTO`,
conserva la primera `fecha_visualizacion` y crea un único evento
`DOCUMENTO_VISUALIZADO`; las solicitudes posteriores son idempotentes. Un
destinatario `FIRMADO` no retrocede ni genera una visualización tardía. Si el
registro técnico falla, el visor no se bloquea y la firma directa conserva las
reglas existentes.

El evento confirma que el visor autenticado renderizó al menos una página. No
demuestra que una persona haya leído o comprendido el documento.

## PDF.js local

El editor y la pantalla de firma utilizan PDF.js `3.11.174` desde
`static/vendor/pdfjs/3.11.174/`, sin solicitar la librería ni el worker a un
CDN. Se incorporan únicamente `pdf.min.js`, `pdf.worker.min.js` y `LICENSE`,
obtenidos del paquete oficial verificable `pdfjs-dist@3.11.174`. PDF.js se
distribuye bajo Apache License 2.0. La librería y el worker pertenecen a la
misma versión, y las URLs del worker se generan con `{% static %}` para respetar
`STATIC_URL` y posibles prefijos de despliegue. La integración desactiva la
evaluación dinámica de fuentes mediante `isEvalSupported: false`.

La configuración de estáticos y `collectstatic` se describe en la sección de
ejecución local; el servidor de desarrollo sirve los archivos desde `static/`.

## Correo electrónico

Actualmente el MVP no utiliza verificación de correo porque el entorno de
despliegue disponible no proporciona un remitente/servicio SMTP para esta
función. El registro público crea una cuenta funcional que puede iniciar sesión
inmediatamente; el sistema no genera tokens ni envía mensajes de verificación.

La configuración SMTP general se conserva en `config/settings.py` y
`.env.example` para posibles funcionalidades futuras, pero no se utiliza en el
flujo actual del MVP.

## Administración de cargos y comités

La gestión organizacional reutiliza Django Admin en `/admin/`. Los cargos
`PRESIDENTE` y `SECRETARIO` son roles funcionales de remitente y no conceden
acceso administrativo.
Para ingresar al Admin, una cuenta debe tener `is_staff=True` y permisos Django
explícitos. Un gestor organizacional requiere, como mínimo:

- `usuarios.view_usuario` para consultar y buscar usuarios.
- `usuarios.change_usuario` para modificar comité y cargo.
- `usuarios.view_cargo` y `usuarios.view_comite` para consultar los catálogos.
- `auditoria.view_eventoauditoria` para consultar el historial.

Estos permisos no se asignan durante el registro público. Deben ser otorgados
por un superusuario a una cuenta administrativa identificada. Para gestores no
superusuarios, el formulario de usuario permite modificar únicamente el comité
y el cargo; nombre, apellido, correo y estado se muestran como referencia. No
expone contraseña, `is_staff`, `is_superuser`, grupos ni permisos individuales.
Los catálogos de cargos y comités y los eventos de auditoría son de solo lectura
para estos gestores.

Cada cambio efectivo de comité o cargo genera un evento inmutable que conserva
el administrador, el usuario afectado y los valores anteriores y nuevos. El
cambio y su auditoría participan en la misma transacción. Guardar sin cambios o
rechazar una asignación inválida no genera un evento exitoso.

Los cambios de cargo se aplican en las comprobaciones de backend desde la
siguiente solicitud. No transfieren documentos, envíos, firmas ni auditorías.
Un antiguo remitente conserva la propiedad y las vistas históricas permitidas
por las reglas actuales, pero pierde las operaciones reservadas a los cargos
`PRESIDENTE` y `SECRETARIO`. El alcance exacto de acceso a documentos anteriores
debe revisarse si la empresa requiere una política distinta en el futuro.

### Riesgo funcional aceptado

Por decisión funcional comunicada por la empresa, el registro público conserva
los cinco cargos y el cargo elegido tiene efecto inmediato. Esto incluye
`PRESIDENTE` y `SECRETARIO`; la administración posterior no elimina el riesgo
previo a esa revisión.

Condiciones para explotarlo:

- Poder acceder al formulario público.
- Proporcionar una dirección con formato `@adicla.org.gt`.
- Elegir un comité oficial sin otro usuario con el mismo cargo directivo.
- Completar las validaciones normales de la cuenta.

Consecuencias potenciales:

- Obtener inmediatamente las funciones documentales de remitente.
- Cargar documentos y preparar envíos para el comité seleccionado.
- Ocupar la restricción única del cargo e impedir otro registro equivalente.

Controles técnicos existentes:

- Solo se aceptan el dominio configurado, comités oficiales activos y los cinco
  cargos definidos.
- PostgreSQL impide más de un presidente o secretario por comité.
- Las operaciones documentales validan el cargo y la propiedad en el backend.
- Un remitente no obtiene `is_staff`, `is_superuser` ni permisos Django.
- Un administrador autorizado puede corregir posteriormente el cargo o comité,
  y el cambio queda auditado.

Limitaciones de estos controles:

- El formato del correo no verifica la identidad ni la posesión de una cuenta
  institucional.
- La unicidad evita repetir el cargo directivo, pero no valida al primer registro.
- Corregir el cargo después del registro no revierte acciones ya realizadas ni
  elimina el acceso que existió antes de la corrección.

La empresa decidió mantener este comportamiento público por razones
funcionales. El riesgo permanece abierto y no constituye una autorización de
seguridad adicional. Como mitigación futura se recomienda verificación real de
identidad institucional, invitaciones o revisión previa para cargos directivos,
sin que esas medidas formen parte del alcance actual.

## Despliegue futuro — Pendiente de implementación

La configuración para Passenger/cPanel se conserva para un posible despliegue
posterior. **No es la modalidad de entrega operativa**: quedan pendientes la
resolución del enrutamiento con LiteSpeed/Passenger y WordPress y su validación
completa en el hosting.

La aplicación Python de cPanel usaría el directorio de `manage.py` como
*Application root*, `passenger_wsgi.py` como *Startup file* y `application`
como *Entry point*. Passenger reutiliza `config/wsgi.py`. Para ese entorno se
recomienda Python 3.12 y un entorno virtual propio. Instale las dependencias
fijadas con el mismo intérprete que ejecutaría Passenger:

```bash
python --version
python -m pip install -r requirements.txt
python -m pip check
```

Antes de activar ese despliegue futuro habrá que definir variables de entorno
de producción (`DJANGO_DEBUG=False`, clave secreta, hosts, orígenes CSRF y
PostgreSQL), `DJANGO_STATIC_ROOT`, `DJANGO_PUBLIC_ROOT` y un
`DJANGO_MEDIA_ROOT` absoluto fuera del directorio público. Habrá que ejecutar
`collectstatic`, servir los estáticos bajo `DJANGO_STATIC_URL` y utilizar el
reinicio de aplicación de cPanel tras cambios. `.env.example` solo contiene
referencias comentadas para esas rutas; los valores efectivos dependerán del
hosting. Estas instrucciones no acreditan que cPanel ya funcione.
