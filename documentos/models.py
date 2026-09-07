import hashlib

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from .validators import validar_pdf


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


class DestinatarioDocumento(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        VISTO = "VISTO", "Visto"

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
