import hashlib
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from .validators import validar_pdf


def ruta_documento_resultado(instance, filename):
    fecha = instance.fecha_generacion or timezone.now()
    return f"documentos_resultados/{fecha:%Y/%m}/{uuid.uuid4().hex}.pdf"


class Documento(models.Model):
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    archivo = models.FileField(
        upload_to="documentos/%Y/%m/",
        validators=[FileExtensionValidator(["pdf"]), validar_pdf],
    )
    nombre_original = models.CharField(max_length=255)
    tamano = models.PositiveBigIntegerField()
    hash_sha256 = models.CharField(max_length=64, editable=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-fecha_creacion",)
        verbose_name = "documento"
        verbose_name_plural = "documentos"

    def __str__(self):
        return self.nombre_original

    def save(self, *args, **kwargs):
        if self.archivo:
            self.archivo.seek(0)
            contenido = self.archivo.read()
            self.tamano = len(contenido)
            self.hash_sha256 = hashlib.sha256(contenido).hexdigest()
            self.archivo.seek(0)
            if not self.nombre_original:
                self.nombre_original = self.archivo.name
        return super().save(*args, **kwargs)


class EnvioDocumento(models.Model):
    class Estado(models.TextChoices):
        PREPARACION = "PREPARACION", "En preparación"
        ENVIADO = "ENVIADO", "Enviado"

    documento = models.OneToOneField(
        Documento,
        on_delete=models.CASCADE,
        related_name="envio",
    )
    remitente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="envios_documentos",
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.ENVIADO,
    )
    fecha_envio = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha_envio",)
        verbose_name = "envio de documento"
        verbose_name_plural = "envios de documentos"

    def __str__(self):
        return f"{self.documento} - {self.get_estado_display()}"


class DocumentoResultado(models.Model):
    envio = models.OneToOneField(
        EnvioDocumento,
        on_delete=models.CASCADE,
        related_name="resultado",
    )
    archivo = models.FileField(upload_to=ruta_documento_resultado)
    hash_sha256 = models.CharField(max_length=64, editable=False)
    tamano = models.PositiveBigIntegerField(editable=False)
    fecha_generacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha_generacion",)
        verbose_name = "documento resultado"
        verbose_name_plural = "documentos resultado"

    def __str__(self):
        return f"Resultado firmado de {self.envio.documento}"


class DestinatarioDocumento(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        PENDIENTE = "PENDIENTE", "Pendiente"
        VISTO = "VISTO", "Visto"
        FIRMADO = "FIRMADO", "Firmado"

    envio = models.ForeignKey(
        EnvioDocumento,
        on_delete=models.CASCADE,
        related_name="destinatarios",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documentos_recibidos",
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha_agregado = models.DateTimeField(auto_now_add=True)
    fecha_visualizacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-fecha_agregado",)
        verbose_name = "destinatario de documento"
        verbose_name_plural = "destinatarios de documentos"
        constraints = [
            models.UniqueConstraint(
                fields=("envio", "usuario"),
                name="destinatario_unico_por_envio",
            )
        ]

    def __str__(self):
        return f"{self.usuario} - {self.envio.documento}"


class CampoFirma(models.Model):
    destinatario = models.ForeignKey(
        DestinatarioDocumento,
        on_delete=models.CASCADE,
        related_name="campos_firma",
    )
    pagina = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    x = models.DecimalField(
        max_digits=7,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    y = models.DecimalField(
        max_digits=7,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    ancho = models.DecimalField(
        max_digits=7,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0.000001")), MaxValueValidator(Decimal("1"))],
    )
    alto = models.DecimalField(
        max_digits=7,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0.000001")), MaxValueValidator(Decimal("1"))],
    )

    class Meta:
        ordering = ("pagina", "id")
        verbose_name = "campo de firma"
        verbose_name_plural = "campos de firma"
        constraints = [
            models.UniqueConstraint(
                fields=("destinatario",),
                name="campo_firma_unico_por_destinatario",
            ),
            models.CheckConstraint(
                condition=models.Q(x__gte=0, x__lte=1, y__gte=0, y__lte=1),
                name="campo_firma_posicion_normalizada",
            ),
            models.CheckConstraint(
                condition=models.Q(ancho__gt=0, ancho__lte=1, alto__gt=0, alto__lte=1),
                name="campo_firma_dimension_normalizada",
            ),
            models.CheckConstraint(
                condition=models.Q(pagina__gte=1),
                name="campo_firma_pagina_positiva",
            ),
            models.CheckConstraint(
                condition=models.Q(x__lte=1 - models.F("ancho")),
                name="campo_firma_dentro_ancho_pagina",
            ),
            models.CheckConstraint(
                condition=models.Q(y__lte=1 - models.F("alto")),
                name="campo_firma_dentro_alto_pagina",
            ),
        ]

    @property
    def documento(self):
        return self.destinatario.envio.documento

    def clean(self):
        super().clean()
        if self.x is not None and self.ancho is not None and self.x + self.ancho > 1:
            raise ValidationError({"ancho": "El campo excede el ancho de la página."})
        if self.y is not None and self.alto is not None and self.y + self.alto > 1:
            raise ValidationError({"alto": "El campo excede el alto de la página."})

    def __str__(self):
        return f"Firma para {self.destinatario.usuario} en página {self.pagina}"
