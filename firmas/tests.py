import base64
import shutil
import struct
import tempfile
import zlib
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documentos.models import DestinatarioDocumento, Documento, EnvioDocumento
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
        self.assertContains(response, "profile-signature-2", count=2)
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
