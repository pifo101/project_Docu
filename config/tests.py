from django.conf import settings
from django.db import connection
from django.test import TestCase


class PostgreSQLBackendTests(TestCase):
    def test_suite_uses_expected_postgresql_database(self):
        expected_test_database = settings.DATABASES["default"]["TEST"]["NAME"]

        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.postgresql",
        )
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.settings_dict["NAME"], expected_test_database)
        self.assertNotEqual(
            connection.settings_dict["NAME"],
            "docu_postgres_dev",
        )

    def test_migrations_create_postgresql_native_types(self):
        expected_types = {
            ("auditoria_eventoauditoria", "direccion_ip"): "inet",
            ("auditoria_eventoauditoria", "informacion_adicional"): "jsonb",
            ("firmas_firma", "imagen"): "bytea",
            ("firmas_firmaperfil", "imagen"): "bytea",
        }

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, udt_name "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND (table_name, column_name) IN ("
                "('auditoria_eventoauditoria', 'direccion_ip'), "
                "('auditoria_eventoauditoria', 'informacion_adicional'), "
                "('firmas_firma', 'imagen'), "
                "('firmas_firmaperfil', 'imagen'))"
            )

            actual_types = {
                (table, column): data_type
                for table, column, data_type in cursor.fetchall()
            }

        self.assertEqual(actual_types, expected_types)
