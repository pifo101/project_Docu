# ADICLA Sign

## PostgreSQL local

PostgreSQL es el motor oficial del proyecto. Django 5.2 requiere PostgreSQL 14
o posterior; el entorno local validado utiliza PostgreSQL 17 y Psycopg 3 con
la implementación binaria.

Instale las dependencias dentro del entorno virtual:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

La base y el rol deben crearse como administrador de PostgreSQL. El rol de la
aplicación debe ser propietario de su base y esquema, pero no debe conservar
`SUPERUSER`, `CREATEDB` ni `CREATEROLE`:

```sql
CREATE ROLE docu_postgres_dev_user LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password docu_postgres_dev_user
CREATE DATABASE docu_postgres_dev OWNER docu_postgres_dev_user ENCODING 'UTF8' TEMPLATE template0;
\connect docu_postgres_dev
ALTER SCHEMA public OWNER TO docu_postgres_dev_user;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO docu_postgres_dev_user;
```

Configure `.env` a partir de `.env.example`. `DB_PASSWORD` debe contener la
contraseña local del rol y nunca debe versionarse. Las variables de base son:

```dotenv
DB_ENGINE=postgresql
DB_NAME=docu_postgres_dev
DB_USER=docu_postgres_dev_user
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=5432
DB_TEST_NAME=test_docu_postgres_dev
```

Antes de cualquier migración o prueba, verifique la configuración efectiva y
el destino que reporta el propio servidor:

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
`--require-empty-schema`. Después de verificar el destino:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe scripts\verify_postgresql_target.py `
  --database docu_postgres_dev `
  --test-database test_docu_postgres_dev `
  --inspect-schema
```

### Pruebas seguras

Django crea y elimina `test_docu_postgres_dev`; nunca utiliza
`docu_postgres_dev` como base de pruebas. El rol de desarrollo recibe
`CREATEDB` solo durante la ejecución de la suite:

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

`mssql-django` y `pyodbc` se conservan temporalmente para el entorno histórico,
pero no son el backend oficial ni deben utilizarse para migraciones o pruebas
de esta rama.

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
