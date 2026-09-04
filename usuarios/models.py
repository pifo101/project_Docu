from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


INSTITUTIONAL_EMAIL_DOMAIN = "adicla.org.gt"


def normalize_institutional_email(email):
    return email.strip().casefold()


def validate_institutional_email(email):
    _, separator, domain = email.rpartition("@")
    if not separator or domain.casefold() != INSTITUTIONAL_EMAIL_DOMAIN:
        raise ValidationError(
            "Ingrese un correo institucional @adicla.org.gt.",
            code="invalid_institutional_domain",
        )


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        return self.get(email=normalize_institutional_email(email))

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")

        email = normalize_institutional_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean(validate_constraints=False)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


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
    username = None
    email = models.EmailField(
        "correo electrónico",
        unique=True,
        validators=[validate_institutional_email],
    )
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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "comite", "cargo"]

    objects = UsuarioManager()

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
        return self.get_full_name() or self.email

    def clean(self):
        super().clean()
        self.email = normalize_institutional_email(self.email)

    def save(self, *args, **kwargs):
        self.email = normalize_institutional_email(self.email)
        validate_institutional_email(self.email)
        return super().save(*args, **kwargs)
