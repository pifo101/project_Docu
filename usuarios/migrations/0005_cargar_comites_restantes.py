from django.db import migrations


def cargar_comites_restantes(apps, schema_editor):
    Comite = apps.get_model("usuarios", "Comite")
    for nombre in ("Dirección Ejecutiva", "Secretaría", "Finanzas"):
        Comite.objects.get_or_create(nombre=nombre)


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0004_cargar_comites_iniciales"),
    ]

    operations = [
        migrations.RunPython(cargar_comites_restantes, migrations.RunPython.noop),
    ]
