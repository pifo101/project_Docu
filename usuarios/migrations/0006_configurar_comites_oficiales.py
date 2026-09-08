from django.db import migrations


OFFICIAL_COMMITTEES = (
    ("Recursos Humanos", "COMITÉ DE LIDERAZGO Y MOTIVACIÓN"),
    ("Tecnología", "COMITÉ DE COMUNICACIÓN"),
    ("Finanzas", "COMITÉ DE TRABAJO EN EQUIPO"),
)
DIRECTIVE_ROLES = ("PRESIDENTE", "VICEPRESIDENTE", "SECRETARIO", "TESORERO")


def configurar_comites_oficiales(apps, schema_editor):
    Comite = apps.get_model("usuarios", "Comite")
    Usuario = apps.get_model("usuarios", "Usuario")
    db_alias = schema_editor.connection.alias

    for historical_name, official_name in OFFICIAL_COMMITTEES:
        historical = (
            Comite.objects.using(db_alias).filter(nombre=historical_name).first()
        )
        official = Comite.objects.using(db_alias).filter(nombre=official_name).first()

        if official is None and historical is not None:
            historical.nombre = official_name
            historical.activo = True
            historical.save(using=db_alias, update_fields=("nombre", "activo"))
            official = historical
            historical = None
        elif official is None:
            official = Comite.objects.using(db_alias).create(
                nombre=official_name,
                activo=True,
            )
        elif not official.activo:
            official.activo = True
            official.save(using=db_alias, update_fields=("activo",))

        if official.nombre != official_name:
            official.nombre = official_name
            official.save(using=db_alias, update_fields=("nombre",))

        if historical is not None and historical.pk != official.pk:
            historical_users = Usuario.objects.using(db_alias).filter(
                comite_id=historical.pk
            )
            historical_users.exclude(cargo_id__in=DIRECTIVE_ROLES).update(
                comite_id=official.pk
            )
            for role in DIRECTIVE_ROLES:
                if not Usuario.objects.using(db_alias).filter(
                    comite_id=official.pk,
                    cargo_id=role,
                ).exists():
                    historical_users.filter(cargo_id=role).update(
                        comite_id=official.pk
                    )
            historical.activo = False
            historical.save(using=db_alias, update_fields=("activo",))

    official_names = tuple(name for _, name in OFFICIAL_COMMITTEES)
    Comite.objects.using(db_alias).filter(nombre__in=official_names).update(activo=True)
    Comite.objects.using(db_alias).exclude(nombre__in=official_names).update(activo=False)


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0005_cargar_comites_restantes"),
    ]

    operations = [
        migrations.RunPython(configurar_comites_oficiales, migrations.RunPython.noop),
    ]
