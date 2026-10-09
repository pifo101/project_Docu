import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Verify Django's effective PostgreSQL connection target."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--test-database", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--require-empty-schema", action="store_true")
    parser.add_argument("--require-test-database-absent", action="store_true")
    parser.add_argument("--inspect-schema", action="store_true")
    createdb_group = parser.add_mutually_exclusive_group()
    createdb_group.add_argument("--require-createdb", action="store_true")
    createdb_group.add_argument("--require-no-createdb", action="store_true")
    return parser.parse_args()


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main():
    args = parse_args()

    import django

    django.setup()

    from django.conf import settings
    from django.db import connection

    config = settings.DATABASES["default"]
    configured_test_database = config.get("TEST", {}).get("NAME")
    expected = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": args.database,
        "HOST": args.host,
        "PORT": args.port,
        "TEST.NAME": args.test_database,
    }
    actual = {
        "ENGINE": config.get("ENGINE"),
        "NAME": config.get("NAME"),
        "HOST": config.get("HOST"),
        "PORT": str(config.get("PORT")),
        "TEST.NAME": configured_test_database,
    }

    for key, expected_value in expected.items():
        if actual[key] != expected_value:
            fail(f"{key} is {actual[key]!r}; expected {expected_value!r}")

    if connection.vendor != "postgresql":
        fail(
            f"connection.vendor is {connection.vendor!r}; expected 'postgresql'"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_user, "
            "inet_server_addr()::text, inet_server_port()"
        )
        database, user, server_address, server_port = cursor.fetchone()

        if args.require_empty_schema:
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [row[0] for row in cursor.fetchall()]
            if tables:
                fail("public schema is not empty: " + ", ".join(tables))

        if args.require_test_database_absent:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                [args.test_database],
            )
            if cursor.fetchone():
                fail(f"test database {args.test_database!r} already exists")

        if args.require_createdb or args.require_no_createdb:
            cursor.execute(
                "SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user"
            )
            can_create_database = cursor.fetchone()[0]
            if args.require_createdb and not can_create_database:
                fail("current user does not have the temporary CREATEDB privilege")
            if args.require_no_createdb and can_create_database:
                fail("current user still has the CREATEDB privilege")

    if database != args.database:
        fail(f"server database is {database!r}; expected {args.database!r}")
    if server_port != int(args.port):
        fail(f"server port is {server_port!r}; expected {args.port!r}")

    print("PostgreSQL target verified")
    print(f"  engine: {actual['ENGINE']}")
    print(f"  vendor: {connection.vendor}")
    print(f"  database: {database}")
    print(f"  test database: {configured_test_database}")
    print(f"  host: {actual['HOST']} ({server_address})")
    print(f"  port: {server_port}")
    print(f"  user: {user}")

    if args.inspect_schema:
        from usuarios.models import Cargo, Comite

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT app, count(*) FROM django_migrations "
                "WHERE app IN ('usuarios', 'documentos', 'firmas', 'auditoria') "
                "GROUP BY app ORDER BY app"
            )
            print(f"  project migrations: {cursor.fetchall()}")

            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [row[0] for row in cursor.fetchall()]
            print(f"  tables ({len(tables)}): {', '.join(tables)}")

            cursor.execute(
                "SELECT table_name, column_name, udt_name, "
                "numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND ("
                "(table_name IN ('firmas_firma', 'firmas_firmaperfil') "
                "AND column_name = 'imagen') OR "
                "(table_name = 'auditoria_eventoauditoria' "
                "AND column_name IN ('direccion_ip', 'informacion_adicional')) OR "
                "(table_name = 'documentos_campofirma' "
                "AND column_name IN ('x', 'y', 'ancho', 'alto'))) "
                "ORDER BY table_name, column_name"
            )
            print(f"  key types: {cursor.fetchall()}")

            cursor.execute(
                "SELECT count(*) FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace "
                "AND NOT convalidated"
            )
            print(f"  unvalidated constraints: {cursor.fetchone()[0]}")

            cursor.execute(
                "SELECT count(*) FROM pg_index i "
                "JOIN pg_class t ON t.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND NOT (i.indisvalid AND i.indisready AND i.indislive)"
            )
            print(f"  invalid indexes: {cursor.fetchone()[0]}")

        print(
            "  cargos: "
            f"{list(Cargo.objects.order_by('id').values_list('codigo', 'es_directivo'))}"
        )
        print(
            "  comites: "
            f"{list(Comite.objects.order_by('nombre').values_list('nombre', 'activo'))}"
        )


if __name__ == "__main__":
    main()
