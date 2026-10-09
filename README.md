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
