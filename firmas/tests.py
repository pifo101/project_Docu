import base64
import shutil
import struct
import tempfile
import zlib
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documentos.models import DestinatarioDocumento, Documento, EnvioDocumento
from usuarios.models import Cargo, Comite

from .forms import FIRMA_MAX_BYTES
from .models import Firma


def png_data_url(visible=True):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    image = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x08\x24\x6f\xff" if visible else b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(image).decode("ascii")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FirmaFlujoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nombre="Comite de firma")
        cls.otro_comite = Comite.objects.create(nombre="Comite externo de firma")
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.presidente = cls._usuario("presidente-firma", cls.comite, presidente)
        cls.destinatario = cls._usuario("destinatario-firma", cls.comite, miembro)
        cls.no_destinatario = cls._usuario("no-destinatario", cls.comite, miembro)
        cls.externo = cls._usuario("externo-firma", cls.otro_comite, miembro)
        cls.documento = Documento.objects.create(
            propietario=cls.presidente,
            archivo=SimpleUploadedFile(
                "acuerdo.pdf", b"%PDF-1.7\nacuerdo", content_type="application/pdf"
            ),
            nombre_original="acuerdo.pdf",
        )
        cls.envio = EnvioDocumento.objects.create(
            documento=cls.documento,
            remitente=cls.presidente,
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def _usuario(cls, nombre, comite, cargo):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name=nombre,
            last_name="Prueba",
            comite=comite,
            cargo=cargo,
        )

    def setUp(self):
        self.solicitud = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=self.destinatario,
        )
        self.url = reverse("firmas:recipient_sign", args=[self.solicitud.pk])

    def _post(self, **changes):
        data = {"firma": png_data_url(), "consentimiento": "1"}
        data.update(changes)
        self.client.force_login(self.destinatario)
        return self.client.post(self.url, data)

    def test_destinatario_puede_acceder_y_la_revision_marca_visto(self):
        self.client.force_login(self.destinatario)

        response = self.client.get(self.url)
        self.solicitud.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "acuerdo.pdf")
        self.assertContains(response, str(self.presidente))
        self.assertContains(response, "data-signature-canvas")
        self.assertContains(response, "Registrar firma y aceptación")
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.VISTO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_usuario_del_mismo_comite_que_no_es_destinatario_no_puede_acceder(self):
        self.client.force_login(self.no_destinatario)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"firma": png_data_url()}).status_code, 404)

    def test_usuario_de_otro_comite_no_puede_acceder_ni_abrir_pdf(self):
        self.client.force_login(self.externo)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("documentos:received_document", args=[self.solicitud.pk])
            ).status_code,
            404,
        )

    def test_presidente_no_puede_firmar_por_destinatario(self):
        self.client.force_login(self.presidente)
        response = self.client.post(
            self.url,
            {"firma": png_data_url(), "consentimiento": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Firma.objects.exists())

    def test_firma_valida_registra_datos_y_cambia_estado(self):
        response = self._post()
        firma = Firma.objects.get()
        self.solicitud.refresh_from_db()

        self.assertRedirects(response, reverse("documentos:user_completed"))
        self.assertEqual(firma.destinatario, self.solicitud)
        self.assertTrue(firma.consentimiento)
        self.assertIsNotNone(firma.fecha_firma)
        self.assertEqual(firma.formato, "image/png")
        self.assertTrue(bytes(firma.imagen).startswith(b"\x89PNG"))
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_fecha_visualizacion_existente_se_conserva(self):
        fecha_original = timezone.now() - timedelta(days=1)
        self.solicitud.estado = DestinatarioDocumento.Estado.VISTO
        self.solicitud.fecha_visualizacion = fecha_original
        self.solicitud.save(update_fields=("estado", "fecha_visualizacion"))

        self._post()
        self.solicitud.refresh_from_db()

        self.assertEqual(self.solicitud.fecha_visualizacion, fecha_original)

    def test_post_directo_desde_pendiente_registra_visualizacion_y_firma(self):
        self._post()
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_sin_consentimiento_no_firma(self):
        response = self._post(consentimiento="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo registrar la firma")
        self.assertFalse(Firma.objects.exists())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.PENDIENTE)

    def test_firma_vacia_se_rechaza(self):
        response = self._post(firma="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_imagen_transparente_se_rechaza_como_firma_vacia(self):
        response = self._post(firma=png_data_url(visible=False))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_base64_invalido_se_rechaza(self):
        response = self._post(firma="data:image/png;base64,no-es-base64***")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "base64 inválidos")
        self.assertFalse(Firma.objects.exists())

    def test_formato_no_admitido_se_rechaza(self):
        response = self._post(firma="data:image/jpeg;base64," + base64.b64encode(b"jpeg").decode())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "imagen PNG válida")
        self.assertFalse(Firma.objects.exists())

    def test_png_malformado_se_rechaza(self):
        malformed = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\ninvalid").decode()
        response = self._post(firma=malformed)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_firma_excesivamente_grande_se_rechaza(self):
        oversized = "data:image/png;base64," + base64.b64encode(
            b"x" * (FIRMA_MAX_BYTES + 1)
        ).decode("ascii")
        response = self._post(firma=oversized)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "excede el tamaño permitido")
        self.assertFalse(Firma.objects.exists())

    def test_no_se_puede_firmar_dos_veces(self):
        self._post()
        response = self.client.post(
            self.url,
            {"firma": png_data_url(), "consentimiento": "1"},
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(reverse("documentos:user_completed"), 302)],
        )
        self.assertEqual(Firma.objects.count(), 1)
        self.assertContains(response, "Ya registraste tu firma")

    def test_dos_post_consecutivos_no_crean_dos_firmas(self):
        self._post()
        self._post()
        self.assertEqual(Firma.objects.filter(destinatario=self.solicitud).count(), 1)

    def test_relacion_uno_a_uno_impide_duplicados_en_base_de_datos(self):
        Firma.objects.create(
            destinatario=self.solicitud,
            imagen=b"primera",
            consentimiento=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Firma.objects.create(
                destinatario=self.solicitud,
                imagen=b"segunda",
                consentimiento=True,
            )

    def test_base_de_datos_exige_consentimiento(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Firma.objects.create(
                destinatario=self.solicitud,
                imagen=b"firma",
                consentimiento=False,
            )

    def test_error_al_crear_firma_revierte_cambio_de_estado(self):
        self.solicitud.estado = DestinatarioDocumento.Estado.VISTO
        self.solicitud.fecha_visualizacion = timezone.now()
        self.solicitud.save(update_fields=("estado", "fecha_visualizacion"))

        with patch("firmas.view.Firma.objects.create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                self._post()

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.VISTO)
        self.assertFalse(Firma.objects.exists())

    def test_estado_incompatible_no_crea_firma(self):
        DestinatarioDocumento.objects.filter(pk=self.solicitud.pk).update(estado="INVALIDO")
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "INVALIDO")

    def test_anonimo_es_redirigido_al_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response,
            f"{reverse('usuarios:login')}?next={self.url}",
        )

    def test_firmar_no_cambia_propiedad_del_documento(self):
        self._post()
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.propietario, self.presidente)
        self.assertFalse(
            Documento.objects.filter(pk=self.documento.pk, propietario=self.destinatario).exists()
        )

    def test_pendientes_muestra_estado_firmado_sin_accion_de_firma(self):
        self._post()
        response = self.client.get(reverse("documentos:pending"))
        self.assertContains(response, "Firmado", count=2)
        self.assertNotContains(response, "Revisar y firmar")

    def test_propietario_consulta_estados_y_otro_usuario_no(self):
        self.solicitud.estado = DestinatarioDocumento.Estado.VISTO
        self.solicitud.save(update_fields=("estado",))
        detail_url = reverse("documentos:document_detail", args=[self.documento.pk])

        self.client.force_login(self.presidente)
        response = self.client.get(detail_url)
        self.assertContains(response, "Estado de destinatarios")
        self.assertContains(response, f"{self.destinatario} - Visto")

        self.client.force_login(self.no_destinatario)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
