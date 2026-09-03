from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class Comite(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("nombre",)
        verbose_name = "comite"
        verbose_name_plural = "comites"

    def __str__(self):
        return self.nombre


class Cargo(models.Model):
    class Codigo(models.TextChoices):
        PRESIDENTE = "PRESIDENTE", "Presidente"
        VICEPRESIDENTE = "VICEPRESIDENTE", "Vicepresidente"
        SECRETARIO = "SECRETARIO", "Secretario"
        TESORERO = "TESORERO", "Tesorero"
        MIEMBRO = "MIEMBRO", "Miembro"

    codigo = models.CharField(max_length=20, choices=Codigo.choices, unique=True)
    nombre = models.CharField(max_length=50, unique=True)
    es_directivo = models.BooleanField()

    class Meta:
        ordering = ("id",)
        verbose_name = "cargo"
        verbose_name_plural = "cargos"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        codigo__in=(
                            "PRESIDENTE",
                            "VICEPRESIDENTE",
                            "SECRETARIO",
                            "TESORERO",
                        ),
                        es_directivo=True,
                    )
                    | Q(codigo="MIEMBRO", es_directivo=False)
                ),
                name="cargo_codigo_directivo_valido",
            )
        ]

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    comite = models.ForeignKey(
        Comite,
        on_delete=models.PROTECT,
        related_name="usuarios",
    )
    cargo = models.ForeignKey(
        Cargo,
        db_column="cargo_codigo",
        on_delete=models.PROTECT,
        related_name="usuarios",
        to_field="codigo",
    )

    REQUIRED_FIELDS = [*AbstractUser.REQUIRED_FIELDS, "comite", "cargo"]

    class Meta(AbstractUser.Meta):
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            models.UniqueConstraint(
                fields=("comite",),
                condition=Q(cargo=Cargo.Codigo.PRESIDENTE),
                name="un_presidente_por_comite",
            ),
            models.UniqueConstraint(
                fields=("comite",),
                condition=Q(cargo=Cargo.Codigo.VICEPRESIDENTE),
                name="un_vicepresidente_por_comite",
            ),
            models.UniqueConstraint(
                fields=("comite",),
                condition=Q(cargo=Cargo.Codigo.SECRETARIO),
                name="un_secretario_por_comite",
            ),
            models.UniqueConstraint(
                fields=("comite",),
                condition=Q(cargo=Cargo.Codigo.TESORERO),
                name="un_tesorero_por_comite",
            ),
        ]

    def __str__(self):
        return self.get_full_name() or self.username
