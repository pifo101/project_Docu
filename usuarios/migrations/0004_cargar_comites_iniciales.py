from django.db import migrations


def cargar_comites(apps, schema_editor):
    Comite = apps.get_model("usuarios", "Comite")
    for nombre in ("Recursos Humanos", "Tecnología"):
        Comite.objects.get_or_create(nombre=nombre)


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0003_usar_correo_como_identificador"),
    ]

    operations = [
        migrations.RunPython(cargar_comites, migrations.RunPython.noop),
    ]
