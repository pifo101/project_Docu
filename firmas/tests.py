import base64
import shutil
import struct
import tempfile
import zlib
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from documentos.models import (
    CampoFirma,
    DestinatarioDocumento,
    Documento,
    DocumentoResultado,
    EnvioDocumento,
)
from documentos.services import ResultadoPDFError, document_tracking_context
from usuarios.models import Cargo, Comite

from .forms import FIRMA_MAX_BYTES
from .models import Firma, FirmaPerfil


def png_bytes(visible=True, color=(8, 36, 111, 255)):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixel = bytes(color) if visible else b"\x00\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + pixel))
        + chunk(b"IEND", b"")
    )


def png_data_url(visible=True):
    return "data:image/png;base64," + base64.b64encode(
        png_bytes(visible=visible)
    ).decode("ascii")


def png_with_dimensions(width, height):
    image = bytearray(png_bytes())
    image[16:24] = struct.pack(">II", width, height)
    image[29:33] = struct.pack(">I", zlib.crc32(image[12:29]) & 0xFFFFFFFF)
    return bytes(image)


def jpeg_bytes():
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQE"
        "BQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/"
        "2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
        "FBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAACAAIDASIAAhEBAxEB/8QA"
        "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
        "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
        "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
        "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
        "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
        "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
        "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
        "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
        "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU"
        "1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8qiSxJJyT"
        "ySaKKK1rfxJerEtj/9k="
    )


class FirmaPerfilTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comite de perfiles")
        otro_comite = Comite.objects.create(nombre="Otro comite de perfiles")
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        cls.usuario = cls._usuario("perfil", comite, miembro)
        cls.otro = cls._usuario("otro-perfil", otro_comite, miembro)
        cls.presidente = cls._usuario("presidente-perfil", comite, presidente)

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

    def _upload(self, name="firma.png", content=None, user=None):
        self.client.force_login(user or self.usuario)
        return self.client.post(
            reverse("firmas:profile_save"),
            {"imagen": SimpleUploadedFile(name, png_bytes() if content is None else content)},
        )

    def test_usuario_guarda_png_valido(self):
        response = self._upload()
        firma = FirmaPerfil.objects.get(usuario=self.usuario)
        self.assertRedirects(response, reverse("usuarios:profile"))
        self.assertEqual(bytes(firma.imagen), png_bytes())
        self.assertEqual(firma.formato, "image/png")
        self.assertIsNotNone(firma.fecha_creacion)
        self.assertIsNotNone(firma.fecha_actualizacion)

    def test_usuario_guarda_jpeg_valido(self):
        response = self._upload("firma.jpeg", jpeg_bytes())
        firma = FirmaPerfil.objects.get(usuario=self.usuario)
        self.assertRedirects(response, reverse("usuarios:profile"))
        self.assertEqual(bytes(firma.imagen), jpeg_bytes())
        self.assertEqual(firma.formato, "image/jpeg")

    def test_anonimo_no_puede_administrar_ni_visualizar_firma(self):
        routes = (
            ("profile_save", "post"),
            ("profile_delete", "post"),
            ("profile_preview", "get"),
        )
        for route, method in routes:
            response = getattr(self.client, method)(reverse(f"firmas:{route}"))
            self.assertEqual(response.status_code, 302)

    def test_archivo_vacio_se_rechaza(self):
        self._upload(content=b"")
        self.assertFalse(FirmaPerfil.objects.exists())

    @override_settings(FIRMA_PERFIL_MAX_FILE_SIZE=20)
    def test_archivo_demasiado_grande_se_rechaza(self):
        self._upload()
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_archivo_no_png_o_jpeg_se_rechaza(self):
        self._upload("firma.png", b"GIF89a contenido")
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_extension_falsa_se_rechaza(self):
        self._upload("firma.jpg", png_bytes())
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_imagen_corrupta_se_rechaza(self):
        self._upload("firma.png", b"\x89PNG\r\n\x1a\ncorrupta")
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_png_con_filtro_de_fila_invalido_se_rechaza(self):
        image = bytearray(png_bytes())
        invalid_scanline = zlib.compress(b"\x05\x08\x24\x6f\xff")
        idat_offset = image.index(b"IDAT") - 4
        idat_end = idat_offset + 12 + int.from_bytes(image[idat_offset:idat_offset + 4], "big")
        kind = b"IDAT"
        replacement = (
            struct.pack(">I", len(invalid_scanline))
            + kind
            + invalid_scanline
            + struct.pack(">I", zlib.crc32(kind + invalid_scanline) & 0xFFFFFFFF)
        )
        image[idat_offset:idat_end] = replacement
        self._upload("firma.png", bytes(image))
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_jpeg_sintetico_sin_tablas_se_rechaza(self):
        synthetic = (
            b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x01\xff\xd9"
        )
        self._upload("firma.jpg", synthetic)
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_dimensiones_excesivas_se_rechazan(self):
        self._upload("firma.png", png_with_dimensions(2049, 1))
        self.assertFalse(FirmaPerfil.objects.exists())

    def test_previsualizacion_devuelve_solo_firma_propia_y_mime_correcto(self):
        FirmaPerfil.objects.create(usuario=self.usuario, imagen=png_bytes(), formato="image/png")
        FirmaPerfil.objects.create(usuario=self.otro, imagen=jpeg_bytes(), formato="image/jpeg")
        self.client.force_login(self.usuario)

        response = self.client.get(
            reverse("firmas:profile_preview"),
            {"usuario": self.otro.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, png_bytes())
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_usuario_sin_firma_no_puede_visualizar_firma_ajena(self):
        FirmaPerfil.objects.create(usuario=self.otro, imagen=jpeg_bytes(), formato="image/jpeg")
        self.client.force_login(self.usuario)
        response = self.client.get(
            reverse("firmas:profile_preview"),
            {"usuario": self.otro.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_previsualizacion_jpeg_devuelve_mime_correcto(self):
        FirmaPerfil.objects.create(
            usuario=self.usuario,
            imagen=jpeg_bytes(),
            formato="image/jpeg",
        )
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("firmas:profile_preview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, jpeg_bytes())

    def test_reemplazar_firma_actualiza_unico_registro(self):
        self._upload()
        original = FirmaPerfil.objects.get(usuario=self.usuario)
        response = self._upload("nueva.png", png_bytes(color=(80, 20, 10, 255)))
        original.refresh_from_db()

        self.assertRedirects(response, reverse("usuarios:profile"))
        self.assertEqual(FirmaPerfil.objects.filter(usuario=self.usuario).count(), 1)
        self.assertEqual(bytes(original.imagen), png_bytes(color=(80, 20, 10, 255)))

    def test_relacion_uno_a_uno_impide_dos_firmas_de_perfil(self):
        FirmaPerfil.objects.create(usuario=self.usuario, imagen=png_bytes(), formato="image/png")
        with self.assertRaises(IntegrityError), transaction.atomic():
            FirmaPerfil.objects.create(
                usuario=self.usuario,
                imagen=jpeg_bytes(),
                formato="image/jpeg",
            )

    def test_reemplazo_invalido_conserva_firma_anterior(self):
        FirmaPerfil.objects.create(usuario=self.usuario, imagen=png_bytes(), formato="image/png")
        self._upload("corrupta.jpg", b"no es jpeg")
        firma = FirmaPerfil.objects.get(usuario=self.usuario)
        self.assertEqual(bytes(firma.imagen), png_bytes())

    def test_usuario_elimina_solo_su_firma(self):
        FirmaPerfil.objects.create(usuario=self.usuario, imagen=png_bytes(), formato="image/png")
        firma_ajena = FirmaPerfil.objects.create(
            usuario=self.otro, imagen=jpeg_bytes(), formato="image/jpeg"
        )
        self.client.force_login(self.usuario)
        response = self.client.post(
            reverse("firmas:profile_delete"),
            {"usuario": self.otro.pk},
        )
        self.assertRedirects(response, reverse("usuarios:profile"))
        self.assertFalse(FirmaPerfil.objects.filter(usuario=self.usuario).exists())
        self.assertTrue(FirmaPerfil.objects.filter(pk=firma_ajena.pk).exists())

    def test_usuario_no_reemplaza_firma_ajena_al_manipular_post(self):
        firma_ajena = FirmaPerfil.objects.create(
            usuario=self.otro, imagen=jpeg_bytes(), formato="image/jpeg"
        )
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("firmas:profile_save"),
            {
                "usuario": self.otro.pk,
                "imagen": SimpleUploadedFile("propia.png", png_bytes()),
            },
        )
        firma_ajena.refresh_from_db()
        self.assertEqual(bytes(firma_ajena.imagen), jpeg_bytes())
        self.assertTrue(FirmaPerfil.objects.filter(usuario=self.usuario).exists())

    def test_perfil_real_muestra_gestion_de_firma(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("usuarios:profile"))
        self.assertContains(response, "Mi firma guardada")
        self.assertContains(response, 'name="imagen"')
        self.assertContains(response, 'accept="image/png,image/jpeg,.png,.jpg,.jpeg"')

    def test_perfil_de_presidente_reutiliza_la_misma_gestion_de_firma(self):
        self.client.force_login(self.presidente)
        response = self.client.get(reverse("usuarios:profile"))
        self.assertContains(response, "Mi firma guardada")
        self.assertContains(response, reverse("firmas:profile_save"))


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
        self.campo_firma = CampoFirma.objects.create(
            destinatario=self.solicitud,
            pagina=1,
            x=Decimal("0.1"),
            y=Decimal("0.2"),
            ancho=Decimal("0.3"),
            alto=Decimal("0.1"),
        )
        self.url = reverse("firmas:recipient_sign", args=[self.solicitud.pk])

    def _post(self, **changes):
        data = {
            "metodo": Firma.Metodo.DIBUJADA,
            "firma": png_data_url(),
            "consentimiento": "1",
        }
        data.update(changes)
        self.client.force_login(self.destinatario)
        return self.client.post(self.url, data)

    def _usar_pdf_valido(self, paginas=1):
        output = BytesIO()
        writer = PdfWriter()
        for _ in range(paginas):
            writer.add_blank_page(width=612, height=792)
        writer.write(output)
        self.documento.archivo = SimpleUploadedFile(
            "acuerdo-valido.pdf", output.getvalue(), content_type="application/pdf"
        )
        self.documento.save()

    def test_destinatario_puede_acceder_y_la_revision_marca_visto(self):
        self.client.force_login(self.destinatario)

        response = self.client.get(self.url)
        self.solicitud.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "acuerdo.pdf")
        self.assertContains(response, str(self.presidente))
        self.assertContains(response, "data-signature-canvas")
        self.assertContains(response, "Registrar firma y aceptación")
        self.assertContains(response, 'data-protected="true"')
        self.assertContains(response, 'class="recipient-viewer recipient-viewer--protected"')
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.VISTO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_flujo_real_no_habilita_fallback_de_documento_demo(self):
        self.client.force_login(self.destinatario)

        response = self.client.get(self.url)
        script_path = finders.find("js/recipient.js")
        with open(script_path, encoding="utf-8") as script:
            recipient_script = script.read()

        self.assertContains(response, "data-pdf-url")
        self.assertNotContains(response, 'data-demo="true"')
        self.assertIn("if (demo) drawMockDocument();", recipient_script)
        self.assertIn("else showDocumentError();", recipient_script)

    def test_vista_entrega_campo_firma_del_destinatario_autorizado(self):
        self.client.force_login(self.destinatario)
        response = self.client.get(self.url)

        self.assertEqual(response.context["campo_firma"], self.campo_firma)
        self.assertEqual(response.context["campo_firma"].destinatario, self.solicitud)

    def test_campo_firma_de_pagina_tres_llega_al_frontend(self):
        self.campo_firma.pagina = 3
        self.campo_firma.save(update_fields=("pagina",))
        self.client.force_login(self.destinatario)

        response = self.client.get(self.url)

        self.assertEqual(response.context["campos_firma_data"][0]["page"], 3)
        self.assertContains(response, 'id="recipient-signature-fields"')
        self.assertContains(response, '"page": 3')

    def test_parametro_campo_ajeno_no_cambia_campo_autorizado(self):
        solicitud_ajena = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=self.no_destinatario,
        )
        campo_ajeno = CampoFirma.objects.create(
            destinatario=solicitud_ajena,
            pagina=3,
            x=Decimal("0.4"),
            y=Decimal("0.5"),
            ancho=Decimal("0.2"),
            alto=Decimal("0.1"),
        )
        self.client.force_login(self.destinatario)

        response = self.client.get(self.url, {"campo_id": campo_ajeno.pk})

        self.assertEqual(response.context["campo_firma"], self.campo_firma)
        self.assertNotEqual(response.context["campo_firma"], campo_ajeno)

    def test_envio_enviado_sin_campo_no_permite_abrir_ni_firmar(self):
        self.campo_firma.delete()
        self.client.force_login(self.destinatario)

        get_response = self.client.get(self.url)
        post_response = self.client.post(self.url, {
            "metodo": Firma.Metodo.DIBUJADA,
            "firma": png_data_url(),
            "consentimiento": "1",
        })

        self.assertEqual(get_response.status_code, 409)
        self.assertEqual(post_response.status_code, 409)
        self.assertContains(get_response, "no tiene una ubicación de firma", status_code=409)
        self.assertFalse(Firma.objects.exists())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.PENDIENTE)

    def test_template_expone_contrato_para_pdf_completo_y_pagina_objetivo(self):
        self.client.force_login(self.destinatario)
        response = self.client.get(self.url)

        self.assertContains(response, "data-recipient-pages")
        self.assertContains(response, "data-pdf-url")
        self.assertContains(response, '"x": 0.1')
        self.assertContains(response, '"y": 0.2')

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

    def test_destinatario_borrador_de_preparacion_no_puede_firmar(self):
        self.envio.estado = EnvioDocumento.Estado.PREPARACION
        self.envio.save(update_fields=("estado",))
        self.solicitud.estado = DestinatarioDocumento.Estado.BORRADOR
        self.solicitud.save(update_fields=("estado",))
        self.client.force_login(self.destinatario)

        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.post(
                self.url,
                {
                    "metodo": Firma.Metodo.DIBUJADA,
                    "firma": png_data_url(),
                    "consentimiento": "1",
                },
            ).status_code,
            404,
        )
        self.assertFalse(Firma.objects.exists())

    def test_presidente_no_puede_firmar_por_destinatario(self):
        self.client.force_login(self.presidente)
        response = self.client.post(
            self.url,
            {
                "metodo": Firma.Metodo.DIBUJADA,
                "firma": png_data_url(),
                "consentimiento": "1",
            },
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
        self.assertEqual(firma.metodo, Firma.Metodo.DIBUJADA)
        self.assertTrue(bytes(firma.imagen).startswith(b"\x89PNG"))
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_ultima_firma_genera_pdf_resultante_automaticamente(self):
        self._usar_pdf_valido()

        response = self._post()

        self.assertRedirects(response, reverse("documentos:user_completed"))
        resultado = DocumentoResultado.objects.get(envio=self.envio)
        with resultado.archivo.open("rb") as archivo:
            self.assertTrue(archivo.read().startswith(b"%PDF-"))

    def test_resultado_solo_se_genera_despues_del_ultimo_destinatario(self):
        self._usar_pdf_valido(paginas=3)
        segunda = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=self.no_destinatario,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
        )
        CampoFirma.objects.create(
            destinatario=segunda,
            pagina=3,
            x=Decimal("0.4"),
            y=Decimal("0.1"),
            ancho=Decimal("0.3"),
            alto=Decimal("0.1"),
        )

        self._post()
        self.assertFalse(DocumentoResultado.objects.exists())

        self.client.force_login(self.no_destinatario)
        response = self.client.post(
            reverse("firmas:recipient_sign", args=[segunda.pk]),
            {
                "metodo": Firma.Metodo.DIBUJADA,
                "firma": png_data_url(),
                "consentimiento": "1",
            },
        )

        self.assertRedirects(response, reverse("documentos:user_completed"))
        self.assertEqual(DocumentoResultado.objects.filter(envio=self.envio).count(), 1)
        self.assertTrue(CampoFirma.objects.filter(destinatario__envio=self.envio).count(), 2)

    def test_resultado_se_reintenta_si_la_generacion_inicial_falla(self):
        self._usar_pdf_valido()
        with patch(
            "firmas.view.generar_resultado_si_completo",
            side_effect=ResultadoPDFError("fallo transitorio"),
        ):
            response = self._post()

        self.assertRedirects(response, reverse("documentos:user_completed"))
        self.assertFalse(DocumentoResultado.objects.exists())

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["readonly"])
        self.assertContains(response, "Esta vista es de solo lectura")
        self.assertTrue(DocumentoResultado.objects.filter(envio=self.envio).exists())

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

    def test_metodo_desconocido_se_rechaza(self):
        response = self._post(metodo="AJENO")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_post_sin_metodo_se_rechaza(self):
        response = self._post(metodo="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_metodo_dibujada_sigue_requiriendo_firma(self):
        response = self._post(firma="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

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
            {
                "metodo": Firma.Metodo.DIBUJADA,
                "firma": png_data_url(),
                "consentimiento": "1",
            },
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

    def test_firmado_sale_de_pendientes_y_no_ofrece_firmar_de_nuevo(self):
        self._post()
        pending_response = self.client.get(reverse("documentos:user_pending"))
        completed_response = self.client.get(reverse("documentos:user_completed"))

        self.assertNotContains(pending_response, self.documento.nombre_original)
        self.assertContains(completed_response, self.documento.nombre_original)
        self.assertContains(completed_response, "Firmado")
        self.assertNotContains(completed_response, "Revisar")

    def test_propietario_consulta_estados_y_otro_usuario_no(self):
        self.solicitud.estado = DestinatarioDocumento.Estado.VISTO
        self.solicitud.save(update_fields=("estado",))
        detail_url = reverse("documentos:document_detail", args=[self.documento.pk])

        self.client.force_login(self.presidente)
        response = self.client.get(detail_url)
        self.assertContains(response, "Estado de destinatarios")
        self.assertContains(response, str(self.destinatario))
        self.assertContains(response, "Visto")

        self.client.force_login(self.no_destinatario)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_firma_guardada_aparece_como_metodo_disponible(self):
        FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=jpeg_bytes(),
            formato="image/jpeg",
        )
        self.client.force_login(self.destinatario)
        response = self.client.get(self.url)
        self.assertContains(response, "Usar mi firma guardada")
        self.assertContains(response, 'data-signature-tab="PERFIL"')
        self.assertContains(response, 'class="saved-signature-preview"')
        self.assertContains(response, 'data-signature-panel="DIBUJADA" hidden')
        self.assertContains(response, "protected-viewer-1", count=2)
        self.assertFalse(Firma.objects.exists())

    def test_guardar_firma_perfil_no_firma_documento_automaticamente(self):
        self.client.force_login(self.destinatario)
        self.client.post(
            reverse("firmas:profile_save"),
            {"imagen": SimpleUploadedFile("firma.png", png_bytes())},
        )
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.PENDIENTE)
        self.assertFalse(Firma.objects.exists())

    def test_sin_firma_guardada_solo_se_ofrece_dibujar(self):
        self.client.force_login(self.destinatario)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Usar mi firma guardada")
        self.assertContains(response, 'data-signature-tab="PERFIL" disabled')
        self.assertContains(response, "Dibujar firma")

    def test_assets_definen_contrato_de_tabs_metodo_y_overflow(self):
        script_path = finders.find("js/recipient.js")
        css_path = finders.find("css/recipient.css")
        with open(script_path, encoding="utf-8") as script:
            javascript = script.read()
        with open(css_path, encoding="utf-8") as stylesheet:
            css = stylesheet.read()

        self.assertIn('panel.hidden = panel.dataset.signaturePanel !== method;', javascript)
        self.assertIn("signatureMethod.value = method;", javascript)
        self.assertIn('method === "DIBUJADA" ? source : ""', javascript)
        self.assertIn("consentCheckbox.checked = false;", javascript)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn(".saved-signature-preview img", css)
        self.assertIn("grid-template-columns: repeat(2,minmax(0,1fr))", css)
        self.assertNotIn("getPage(1)", javascript)
        self.assertIn("pageNumber <= recipientPdf.numPages", javascript)
        self.assertIn("signatureFieldsData[index]", javascript)
        self.assertIn("fieldData.x * 100", javascript)
        self.assertIn("fieldData.y * 100", javascript)
        self.assertIn('window.addEventListener("resize", scheduleRecipientResize)', javascript)
        self.assertIn('recipientViewer.addEventListener("contextmenu"', javascript)
        self.assertIn('recipientViewer.addEventListener("copy"', javascript)
        self.assertIn('recipientViewer.addEventListener("dragstart"', javascript)
        self.assertIn('document.addEventListener("keydown"', javascript)
        self.assertIn('["s", "p"].includes', javascript)
        self.assertIn(".recipient-viewer--protected .recipient-document", css)
        self.assertIn("@media print", css)
        self.assertIn(".recipient-viewer--protected { display: none !important; }", css)

    def test_metodo_perfil_copia_imagen_y_finaliza_documento(self):
        fecha_original = timezone.now() - timedelta(hours=2)
        self.solicitud.estado = DestinatarioDocumento.Estado.VISTO
        self.solicitud.fecha_visualizacion = fecha_original
        self.solicitud.save(update_fields=("estado", "fecha_visualizacion"))
        perfil = FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=jpeg_bytes(),
            formato="image/jpeg",
        )

        response = self._post(
            metodo=Firma.Metodo.PERFIL,
            firma="data:image/png;base64,contenido-ignorado",
        )
        firma = Firma.objects.get(destinatario=self.solicitud)
        self.solicitud.refresh_from_db()

        self.assertRedirects(response, reverse("documentos:user_completed"))
        self.assertEqual(firma.metodo, Firma.Metodo.PERFIL)
        self.assertEqual(bytes(firma.imagen), bytes(perfil.imagen))
        self.assertEqual(firma.formato, "image/jpeg")
        self.assertTrue(firma.consentimiento)
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertEqual(self.solicitud.fecha_visualizacion, fecha_original)

    def test_firma_perfil_y_campo_firma_permanecen_separados(self):
        campo = self.campo_firma
        perfil = FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=png_bytes(),
            formato="image/png",
        )

        self._post(metodo=Firma.Metodo.PERFIL, firma="")

        firma = Firma.objects.get(destinatario=self.solicitud)
        self.assertEqual(bytes(firma.imagen), bytes(perfil.imagen))
        self.assertTrue(CampoFirma.objects.filter(pk=campo.pk).exists())
        self.assertEqual(campo.destinatario, firma.destinatario)

    def test_metodo_perfil_desde_pendiente_registra_visualizacion(self):
        FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=png_bytes(),
            formato="image/png",
        )
        self._post(metodo=Firma.Metodo.PERFIL, firma="")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertIsNotNone(self.solicitud.fecha_visualizacion)

    def test_metodo_perfil_requiere_consentimiento(self):
        FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=png_bytes(),
            formato="image/png",
        )
        response = self._post(metodo=Firma.Metodo.PERFIL, firma="", consentimiento="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.PENDIENTE)

    def test_usuario_sin_firma_guardada_no_puede_usar_metodo_perfil(self):
        response = self._post(metodo=Firma.Metodo.PERFIL, firma="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes una firma guardada disponible")
        self.assertFalse(Firma.objects.exists())

    def test_no_puede_usar_firma_guardada_de_otro_usuario(self):
        ajena = FirmaPerfil.objects.create(
            usuario=self.no_destinatario,
            imagen=jpeg_bytes(),
            formato="image/jpeg",
        )
        response = self._post(
            metodo=Firma.Metodo.PERFIL,
            firma="",
            firma_perfil_id=ajena.pk,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Firma.objects.exists())

    def test_reemplazar_firma_perfil_no_altera_firma_historica(self):
        FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=png_bytes(),
            formato="image/png",
        )
        self._post(metodo=Firma.Metodo.PERFIL, firma="")
        historica = Firma.objects.get()
        original = bytes(historica.imagen)

        self.client.post(
            reverse("firmas:profile_save"),
            {"imagen": SimpleUploadedFile("nueva.jpeg", jpeg_bytes())},
        )
        historica.refresh_from_db()

        self.assertEqual(bytes(historica.imagen), original)
        self.assertEqual(historica.formato, "image/png")

    def test_eliminar_firma_perfil_no_altera_firma_historica(self):
        FirmaPerfil.objects.create(
            usuario=self.destinatario,
            imagen=jpeg_bytes(),
            formato="image/jpeg",
        )
        self._post(metodo=Firma.Metodo.PERFIL, firma="")
        historica = Firma.objects.get()
        original = bytes(historica.imagen)
        self.client.post(reverse("firmas:profile_delete"))

        historica.refresh_from_db()
        self.solicitud.refresh_from_db()
        self.assertEqual(bytes(historica.imagen), original)
        self.assertEqual(self.solicitud.estado, DestinatarioDocumento.Estado.FIRMADO)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FirmaSinOrdenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nombre="Comite presidente firmante")
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.presidente = cls._usuario("presidente-primero", presidente)
        cls.miembro = cls._usuario("miembro-despues", miembro)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def _usuario(cls, nombre, cargo):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name=nombre,
            last_name="Prueba",
            comite=cls.comite,
            cargo=cargo,
        )

    def setUp(self):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(output)
        self.documento = Documento.objects.create(
            propietario=self.presidente,
            archivo=SimpleUploadedFile(
                "presidente-primero.pdf", output.getvalue(), content_type="application/pdf"
            ),
            nombre_original="presidente-primero.pdf",
        )
        self.envio = EnvioDocumento.objects.create(
            documento=self.documento,
            remitente=self.presidente,
            estado=EnvioDocumento.Estado.ENVIADO,
        )
        self.asignacion_presidente = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=self.presidente,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
        )
        self.asignacion_miembro = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=self.miembro,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
        )
        self._campo(self.asignacion_presidente, "0.10", "0.10")
        self._campo(self.asignacion_presidente, "0.10", "0.30")
        self._campo(self.asignacion_miembro, "0.55", "0.10")

    def _campo(self, destinatario, x, y):
        return CampoFirma.objects.create(
            destinatario=destinatario,
            pagina=1,
            x=Decimal(x),
            y=Decimal(y),
            ancho=Decimal("0.25"),
            alto=Decimal("0.10"),
        )

    def _firmar(self, usuario, destinatario):
        self.client.force_login(usuario)
        return self.client.post(
            reverse("firmas:recipient_sign", args=[destinatario.pk]),
            {
                "metodo": Firma.Metodo.DIBUJADA,
                "firma": png_data_url(),
                "consentimiento": "1",
            },
        )

    def test_presidente_puede_firmar_primero_y_completar_flujo(self):
        miembro_url = reverse(
            "firmas:recipient_sign", args=[self.asignacion_miembro.pk]
        )
        self.client.force_login(self.presidente)
        vista_presidente = self.client.get(
            reverse("firmas:recipient_sign", args=[self.asignacion_presidente.pk])
        )
        self.assertEqual(vista_presidente.status_code, 200)
        self.assertFalse(vista_presidente.context["readonly"])
        self.assertFalse(vista_presidente.context["protected_viewer"])
        self.assertContains(vista_presidente, 'data-protected="false"')
        self.assertEqual(len(vista_presidente.context["campos_firma_data"]), 2)
        self.assertContains(vista_presidente, 'id="recipient-signature-fields"')

        firmado_presidente = self._firmar(
            self.presidente, self.asignacion_presidente
        )
        self.assertRedirects(firmado_presidente, reverse("documentos:user_completed"))
        self.asignacion_presidente.refresh_from_db()
        firma_presidente = Firma.objects.get(destinatario=self.asignacion_presidente)
        self.assertEqual(self.asignacion_presidente.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertEqual(firma_presidente.destinatario.usuario, self.presidente)
        self.assertFalse(DocumentoResultado.objects.exists())

        seguimiento = document_tracking_context(self.documento)
        self.assertEqual(seguimiento["signature_total"], 2)
        self.assertEqual(seguimiento["signature_completed"], 1)
        self.assertEqual(seguimiento["signature_percentage"], 50)
        self.assertFalse(seguimiento["all_signed"])
        self.assertIn(
            f"{self.presidente} firmó el documento",
            [evento["description"] for evento in seguimiento["activity_events"]],
        )

        self._firmar(self.presidente, self.asignacion_presidente)
        self.assertEqual(
            Firma.objects.filter(destinatario=self.asignacion_presidente).count(), 1
        )

        self.client.force_login(self.miembro)
        vista_habilitada = self.client.get(miembro_url)
        self.assertEqual(vista_habilitada.status_code, 200)
        self.assertFalse(vista_habilitada.context["readonly"])
        self.assertTrue(vista_habilitada.context["protected_viewer"])
        self.assertContains(vista_habilitada, 'data-protected="true"')
        self.assertContains(vista_habilitada, "Registrar firma y aceptación")

        firmado_miembro = self._firmar(self.miembro, self.asignacion_miembro)
        self.assertRedirects(firmado_miembro, reverse("documentos:user_completed"))
        self.asignacion_miembro.refresh_from_db()
        self.assertEqual(self.asignacion_miembro.estado, DestinatarioDocumento.Estado.FIRMADO)
        self.assertEqual(Firma.objects.filter(destinatario__envio=self.envio).count(), 2)

        seguimiento = document_tracking_context(self.documento)
        self.assertEqual(seguimiento["signature_completed"], 2)
        self.assertEqual(seguimiento["signature_percentage"], 100)
        self.assertTrue(seguimiento["all_signed"])
        resultado = DocumentoResultado.objects.get(envio=self.envio)
        with resultado.archivo.open("rb") as archivo:
            pagina = PdfReader(BytesIO(archivo.read())).pages[0]
        firmas_dibujadas = sum(
            1 for _, operador in pagina.get_contents().operations if operador == b"Do"
        )
        self.assertEqual(firmas_dibujadas, 3)

        self.client.force_login(self.miembro)
        vista_firmada = self.client.get(miembro_url)
        self.assertEqual(vista_firmada.status_code, 200)
        self.assertTrue(vista_firmada.context["readonly"])
        self.assertEqual(
            vista_firmada.context["pdf_view_url"],
            reverse("documentos:view_result", args=[self.envio.pk]),
        )
        self.assertEqual(vista_firmada.context["campos_firma_data"], [])
        self.assertNotContains(vista_firmada, "Campo de firma asignado")
        self.assertNotContains(vista_firmada, "Descargar")

    def test_dos_miembros_firman_antes_y_presidente_finaliza(self):
        segundo_miembro = get_user_model().objects.create_user(
            email="segundo-sin-orden@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Segundo",
            last_name="Prueba",
            comite=self.comite,
            cargo=self.miembro.cargo,
        )
        asignacion_segundo = DestinatarioDocumento.objects.create(
            envio=self.envio,
            usuario=segundo_miembro,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
        )
        self._campo(asignacion_segundo, "0.55", "0.30")
        miembro_url = reverse(
            "firmas:recipient_sign", args=[self.asignacion_miembro.pk]
        )

        self.client.force_login(self.miembro)
        vista_miembro = self.client.get(miembro_url)
        self.assertEqual(vista_miembro.status_code, 200)
        self.assertFalse(vista_miembro.context["readonly"])
        self.assertContains(vista_miembro, "Registrar firma y aceptación")
        self.assertNotContains(vista_miembro, "presidente remitente haya firmado")
        self.assertNotContains(vista_miembro, "Descargar")
        self.assertEqual(
            self.client.get(reverse("documentos:download", args=[self.documento.pk])).status_code,
            403,
        )

        primera_firma = self._firmar(self.miembro, self.asignacion_miembro)
        self.assertNotEqual(primera_firma.status_code, 409)
        self.assertRedirects(primera_firma, reverse("documentos:user_completed"))
        seguimiento = document_tracking_context(self.documento)
        self.assertEqual(seguimiento["signature_completed"], 1)
        self.assertEqual(seguimiento["signature_total"], 3)
        self.assertEqual(seguimiento["signature_percentage"], 33)
        self.assertFalse(DocumentoResultado.objects.exists())

        segunda_firma = self._firmar(segundo_miembro, asignacion_segundo)
        self.assertNotEqual(segunda_firma.status_code, 409)
        seguimiento = document_tracking_context(self.documento)
        self.assertEqual(seguimiento["signature_completed"], 2)
        self.assertEqual(seguimiento["signature_percentage"], 67)
        self.assertFalse(seguimiento["all_signed"])
        self.assertFalse(DocumentoResultado.objects.exists())

        firma_miembro = Firma.objects.get(destinatario=self.asignacion_miembro)
        firma_segundo = Firma.objects.get(destinatario=asignacion_segundo)
        firma_presidente = self._firmar(self.presidente, self.asignacion_presidente)
        self.assertRedirects(firma_presidente, reverse("documentos:user_completed"))
        firma_presidente_registrada = Firma.objects.get(
            destinatario=self.asignacion_presidente
        )
        self.assertLessEqual(firma_miembro.fecha_firma, firma_segundo.fecha_firma)
        self.assertLessEqual(
            firma_segundo.fecha_firma, firma_presidente_registrada.fecha_firma
        )

        seguimiento = document_tracking_context(self.documento)
        eventos_firma = [
            evento["description"]
            for evento in seguimiento["activity_events"]
            if evento["kind"] == "signed"
        ]
        self.assertEqual(eventos_firma, [
            f"{self.miembro} firmó el documento",
            f"{segundo_miembro} firmó el documento",
            f"{self.presidente} firmó el documento",
        ])
        self.assertEqual(seguimiento["signature_completed"], 3)
        self.assertEqual(seguimiento["signature_percentage"], 100)
        self.assertTrue(seguimiento["all_signed"])
        self.assertEqual(DocumentoResultado.objects.filter(envio=self.envio).count(), 1)

        self._firmar(self.presidente, self.asignacion_presidente)
        self.assertEqual(
            Firma.objects.filter(destinatario=self.asignacion_presidente).count(), 1
        )

        self.client.force_login(self.presidente)
        descarga = self.client.get(
            reverse("documentos:download_result", args=[self.envio.pk])
        )
        self.assertEqual(descarga.status_code, 200)
        self.assertIn("attachment", descarga["Content-Disposition"])

    def test_envio_historico_sin_remitente_destinatario_conserva_flujo(self):
        self.asignacion_presidente.delete()

        response = self._firmar(self.miembro, self.asignacion_miembro)

        self.assertRedirects(response, reverse("documentos:user_completed"))
        self.assertTrue(Firma.objects.filter(destinatario=self.asignacion_miembro).exists())
        self.assertTrue(DocumentoResultado.objects.filter(envio=self.envio).exists())
