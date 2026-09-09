import hashlib
import json
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from usuarios.models import Cargo, Comite

from firmas.models import Firma, FirmaPerfil

from .models import (
    CampoFirma,
    DestinatarioDocumento,
    Documento,
    DocumentoResultado,
    EnvioDocumento,
)
from .services import (
    ResultadoPDFError,
    calcular_colocacion_firma,
    calcular_rectangulo_pdf,
    construir_pdf_resultado,
    envio_esta_completo,
    generar_resultado_si_completo,
)


class DocumentsPageTests(TestCase):
    def test_documents_page_renders_mock_list_and_controls(self):
        response = self.client.get(reverse("documentos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mis documentos")
        self.assertContains(response, "Contrato de servicios 2026")
        self.assertContains(response, 'data-document-search')
        self.assertContains(response, 'data-filter="expired"')
        self.assertContains(response, 'data-empty-state')
        self.assertContains(response, 'data-upload-open', count=3)

    def test_upload_form_and_drop_zone_submit_the_archivo_field(self):
        response = self.client.get(reverse("documentos:list"))

        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="archivo"')
        script_path = finders.find("js/dashboard.js")
        with open(script_path, encoding="utf-8") as script:
            self.assertIn(
                "uploadInput.files = event.dataTransfer.files;",
                script.read(),
            )

    def test_dashboard_links_to_documents_page(self):
        comite = Comite.objects.create(nombre="Comité dashboard documental")
        presidente = get_user_model().objects.create_user(
            email="dashboard-documental@adicla.org.gt",
            password="ClaveSegura!2026",
            comite=comite,
            cargo=Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE),
        )
        self.client.force_login(presidente)

        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertContains(response, f'href="{reverse("documentos:list")}"')
        self.assertNotContains(response, f'data-editor-url="{reverse("documentos:recipients")}"')
        self.assertNotContains(response, "Andrea Morales")

    def test_navegacion_autenticada_no_enlaza_rutas_demo(self):
        comite = Comite.objects.create(nombre="Comité navegación real")
        presidente = get_user_model().objects.create_user(
            email="navegacion-real@adicla.org.gt",
            password="ClaveSegura!2026",
            comite=comite,
            cargo=Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE),
        )
        self.client.force_login(presidente)
        demo_urls = (
            reverse("documentos:detail"),
            reverse("documentos:recipients"),
            reverse("documentos:editor"),
            reverse("documentos:review"),
            reverse("firmas:request"),
        )

        for route_name in ("usuarios:dashboard", "usuarios:profile", "documentos:list"):
            response = self.client.get(reverse(route_name))
            self.assertContains(response, f'href="{reverse("documentos:user_pending")}"')
            self.assertNotContains(response, f'href="{reverse("documentos:pending")}"')
            for demo_url in demo_urls:
                self.assertNotContains(response, f'href="{demo_url}')

    def test_document_detail_page_renders_activity(self):
        response = self.client.get(reverse("documentos:detail"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Detalles del documento")
        self.assertContains(response, "Esperando firma")

    def test_recipients_page_renders_wizard(self):
        response = self.client.get(reverse("documentos:recipients"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seleccionar destinatarios")
        self.assertContains(response, "Una persona")
        self.assertContains(response, "Comité completo")
        self.assertContains(response, "Personas específicas")
        self.assertContains(response, 'data-recipient-form')

    def test_review_page_renders_summary_and_success_dialog(self):
        response = self.client.get(reverse("documentos:review"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revisar y enviar")
        self.assertContains(response, "Enviar solicitud")
        self.assertContains(response, 'data-success-dialog')

    def test_pending_page_requires_authentication(self):
        response = self.client.get(reverse("documentos:pending"))

        self.assertRedirects(
            response,
            f"{reverse('usuarios:login')}?next={reverse('documentos:pending')}",
        )


@override_settings(DOCUMENTO_MAX_FILE_SIZE=20, MEDIA_ROOT=tempfile.mkdtemp())
class DocumentoUploadTests(TestCase):
    def setUp(self):
        comite = Comite.objects.create(nombre="Comité de documentos")
        cargo = Cargo.objects.get(codigo="MIEMBRO")
        self.usuario = self._crear_usuario("propietario", comite, cargo)
        self.otro_usuario = self._crear_usuario("otro", comite, cargo)

    def tearDown(self):
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def _crear_usuario(self, nombre, comite, cargo):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt", password="ClaveSegura!2026",
            first_name=nombre, last_name="Prueba", comite=comite, cargo=cargo,
        )

    def _pdf(self, nombre="archivo.pdf", contenido=b"%PDF-1.7\nok"):
        return SimpleUploadedFile(nombre, contenido, content_type="application/pdf")

    def _subir(self, archivo, usuario=None):
        self.client.force_login(usuario or self.usuario)
        return self.client.post(reverse("documentos:upload"), {"archivo": archivo})

    def test_usuario_puede_subir_pdf_y_se_guardan_metadatos(self):
        contenido = b"%PDF-1.7\nok"
        response = self._subir(self._pdf(contenido=contenido))
        documento = Documento.objects.get()

        self.assertRedirects(response, reverse("documentos:list"))
        self.assertEqual(documento.propietario, self.usuario)
        self.assertEqual(documento.nombre_original, "archivo.pdf")
        self.assertEqual(documento.tamano, len(contenido))
        self.assertEqual(documento.hash_sha256, hashlib.sha256(contenido).hexdigest())
        self.assertTrue(documento.archivo.name.startswith("documentos/"))
        self.assertEqual(documento.archivo.size, len(contenido))

    def test_rechaza_archivo_no_pdf_vacio_y_mayor_al_limite(self):
        for archivo in (
            self._pdf("archivo.txt", b"texto"),
            self._pdf(contenido=b""),
            self._pdf(contenido=b"%PDF-" + b"x" * 20),
        ):
            response = self._subir(archivo)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Documento.objects.count(), 0)

    def test_rechaza_contenido_con_extension_pdf_si_no_es_pdf(self):
        response = self._subir(self._pdf(contenido=b"no es un pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Documento.objects.exists())

    def test_post_sin_archivo_muestra_error_de_campo_obligatorio(self):
        self.client.force_login(self.usuario)
        response = self.client.post(
            reverse("documentos:upload"),
            {"csrfmiddlewaretoken": "token-de-prueba"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].files)
        self.assertIn("archivo", response.context["form"].errors)

    def test_anonimo_no_puede_subir(self):
        response = self.client.get(reverse("documentos:upload"))
        self.assertRedirects(response, f"{reverse('usuarios:login')}?next={reverse('documentos:upload')}")

    def test_listado_y_acceso_estan_limitados_al_propietario(self):
        propio = Documento.objects.create(propietario=self.usuario, archivo=self._pdf("propio.pdf"), nombre_original="propio.pdf")
        ajeno = Documento.objects.create(propietario=self.otro_usuario, archivo=self._pdf("ajeno.pdf"), nombre_original="ajeno.pdf")
        self.client.force_login(self.usuario)

        listado = self.client.get(reverse("documentos:list"))
        self.assertContains(listado, "propio.pdf")
        self.assertNotContains(listado, "ajeno.pdf")
        self.assertEqual(self.client.get(reverse("documentos:document_detail", args=[propio.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("documentos:document_detail", args=[ajeno.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("documentos:download", args=[ajeno.pk])).status_code, 404)

    def test_miembro_no_ve_acciones_de_preparacion_o_envio(self):
        documento = Documento.objects.create(
            propietario=self.usuario,
            archivo=self._pdf("miembro.pdf"),
            nombre_original="miembro.pdf",
        )
        self.client.force_login(self.usuario)

        response = self.client.get(reverse("documentos:list"))

        self.assertNotContains(
            response,
            reverse("documentos:committee_recipients", args=[documento.pk]),
        )
        self.assertNotContains(
            response,
            reverse("documentos:document_editor", args=[documento.pk]),
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EnvioDocumentoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nombre="Comité de envío")
        cls.otro_comite = Comite.objects.create(nombre="Comité externo")
        cls.cargo_presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        cls.cargo_miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.presidente = cls.crear_usuario(
            "presidente", cls.comite, cls.cargo_presidente
        )
        cls.miembro = cls.crear_usuario("miembro", cls.comite, cls.cargo_miembro)
        cls.inactivo = cls.crear_usuario(
            "inactivo", cls.comite, cls.cargo_miembro, is_active=False
        )
        cls.usuario_externo = cls.crear_usuario(
            "externo", cls.otro_comite, cls.cargo_miembro
        )
        cls.documento = Documento.objects.create(
            propietario=cls.presidente,
            archivo=SimpleUploadedFile(
                "acta.pdf", b"%PDF-1.7\nacta", content_type="application/pdf"
            ),
            nombre_original="acta.pdf",
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def crear_usuario(cls, nombre, comite, cargo, **extra_fields):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name=nombre.capitalize(),
            last_name="Prueba",
            comite=comite,
            cargo=cargo,
            **extra_fields,
        )

    def crear_envio(self):
        envio = EnvioDocumento.objects.create(
            documento=self.documento,
            remitente=self.presidente,
        )
        destinatario = DestinatarioDocumento.objects.create(
            envio=envio,
            usuario=self.miembro,
        )
        return envio, destinatario

    def preparar_destinatarios(self):
        self.client.force_login(self.presidente)
        return self.client.post(
            reverse("documentos:committee_recipients", args=[self.documento.pk])
        )

    def preparar_envio_con_campo(self):
        self.preparar_destinatarios()
        envio = EnvioDocumento.objects.get(documento=self.documento)
        destinatario = envio.destinatarios.get(usuario=self.miembro)
        CampoFirma.objects.create(
            destinatario=destinatario,
            pagina=1,
            x=Decimal("0.1"),
            y=Decimal("0.1"),
            ancho=Decimal("0.2"),
            alto=Decimal("0.1"),
        )
        return envio, destinatario

    def test_presidente_envia_documento_a_integrantes_activos_sin_incluirse(self):
        self.preparar_envio_con_campo()
        response = self.client.post(reverse("documentos:send", args=[self.documento.pk]))

        self.assertRedirects(
            response,
            reverse("documentos:document_detail", args=[self.documento.pk]),
        )
        envio = EnvioDocumento.objects.get()
        self.assertEqual(envio.documento, self.documento)
        self.assertEqual(envio.remitente, self.presidente)
        self.assertEqual(envio.estado, EnvioDocumento.Estado.ENVIADO)
        self.assertQuerySetEqual(
            envio.destinatarios.values_list("usuario_id", flat=True),
            [self.miembro.pk],
            ordered=False,
        )
        self.assertFalse(envio.destinatarios.filter(usuario=self.presidente).exists())
        self.assertFalse(envio.destinatarios.filter(usuario=self.inactivo).exists())

    def test_pantallas_reales_muestran_documento_comite_e_integrantes(self):
        self.preparar_destinatarios()

        for nombre_ruta in ("committee_recipients", "send_review"):
            response = self.client.get(
                reverse(f"documentos:{nombre_ruta}", args=[self.documento.pk])
            )
            self.assertContains(response, "acta.pdf")
            self.assertContains(response, self.comite.nombre)
            self.assertContains(response, str(self.miembro))
            self.assertNotContains(response, str(self.inactivo))
            self.assertNotContains(response, str(self.usuario_externo))

    def test_listado_usa_estado_y_rutas_del_envio_real(self):
        self.preparar_envio_con_campo()
        editor_url = reverse("documentos:document_editor", args=[self.documento.pk])
        recipients_url = reverse("documentos:committee_recipients", args=[self.documento.pk])

        preparation = self.client.get(reverse("documentos:list"))
        self.assertContains(preparation, "En preparación")
        self.assertContains(preparation, editor_url)

        self.client.post(reverse("documentos:send", args=[self.documento.pk]))
        sent = self.client.get(reverse("documentos:list"))
        self.assertContains(sent, "Enviado")
        self.assertNotContains(sent, recipients_url)
        self.assertNotContains(sent, editor_url)

    def test_revision_usa_destinatarios_y_campos_preparados(self):
        _, destinatario = self.preparar_envio_con_campo()

        response = self.client.get(
            reverse("documentos:send_review", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(destinatario.usuario))
        self.assertContains(response, "Firma en página 1")
        self.assertTrue(response.context["listo_para_enviar"])

    def test_restriccion_impide_destinatario_duplicado_en_un_envio(self):
        envio, _ = self.crear_envio()

        with self.assertRaises(IntegrityError), transaction.atomic():
            DestinatarioDocumento.objects.create(envio=envio, usuario=self.miembro)

    def test_doble_confirmacion_no_duplica_envio_ni_destinatarios(self):
        self.preparar_envio_con_campo()
        url = reverse("documentos:send", args=[self.documento.pk])

        self.client.post(url)
        self.client.post(url)

        self.assertEqual(EnvioDocumento.objects.count(), 1)
        self.assertEqual(DestinatarioDocumento.objects.count(), 1)

    def test_usuario_no_presidente_no_puede_enviar(self):
        documento = Documento.objects.create(
            propietario=self.miembro,
            archivo=SimpleUploadedFile("miembro.pdf", b"%PDF-1.7\nmiembro"),
            nombre_original="miembro.pdf",
        )
        self.client.force_login(self.miembro)

        response = self.client.post(reverse("documentos:send", args=[documento.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(EnvioDocumento.objects.exists())

    def test_presidente_de_comite_inactivo_no_puede_iniciar_envio(self):
        self.comite.activo = False
        self.comite.save(update_fields=("activo",))
        self.client.force_login(self.presidente)

        response = self.client.post(
            reverse("documentos:committee_recipients", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(EnvioDocumento.objects.exists())

    def test_comite_inactivo_no_puede_confirmar_envio(self):
        envio, destinatario = self.preparar_envio_con_campo()
        self.comite.activo = False
        self.comite.save(update_fields=("activo",))

        response = self.client.post(
            reverse("documentos:send", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 403)
        envio.refresh_from_db()
        destinatario.refresh_from_db()
        self.assertEqual(envio.estado, EnvioDocumento.Estado.PREPARACION)
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.BORRADOR)

    def test_envio_rechaza_destinatario_que_ya_no_pertenece_al_comite(self):
        envio, destinatario = self.preparar_envio_con_campo()
        self.miembro.comite = self.otro_comite
        self.miembro.save(update_fields=("comite",))

        response = self.client.post(
            reverse("documentos:send", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 403)
        envio.refresh_from_db()
        destinatario.refresh_from_db()
        self.assertEqual(envio.estado, EnvioDocumento.Estado.PREPARACION)
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.BORRADOR)

    def test_envio_rechaza_destinatario_desactivado_despues_de_preparar(self):
        envio, destinatario = self.preparar_envio_con_campo()
        self.miembro.is_active = False
        self.miembro.save(update_fields=("is_active",))

        response = self.client.post(
            reverse("documentos:send", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 403)
        envio.refresh_from_db()
        destinatario.refresh_from_db()
        self.assertEqual(envio.estado, EnvioDocumento.Estado.PREPARACION)
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.BORRADOR)

    def test_get_editor_sin_preparacion_no_crea_envio(self):
        self.client.force_login(self.presidente)

        response = self.client.get(
            reverse("documentos:document_editor", args=[self.documento.pk])
        )

        self.assertRedirects(
            response,
            reverse("documentos:committee_recipients", args=[self.documento.pk]),
        )
        self.assertFalse(EnvioDocumento.objects.exists())

    def test_get_editor_sin_preparacion_no_crea_destinatarios(self):
        self.client.force_login(self.presidente)
        EnvioDocumento.objects.create(
            documento=self.documento,
            remitente=self.presidente,
            estado=EnvioDocumento.Estado.PREPARACION,
        )

        response = self.client.get(
            reverse("documentos:document_editor", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DestinatarioDocumento.objects.exists())

    def test_get_editor_no_elimina_destinatarios_ni_campos(self):
        self.preparar_destinatarios()
        envio = EnvioDocumento.objects.get(documento=self.documento)
        destinatario_externo = DestinatarioDocumento.objects.create(
            envio=envio,
            usuario=self.usuario_externo,
            estado=DestinatarioDocumento.Estado.BORRADOR,
        )
        campo = CampoFirma.objects.create(
            destinatario=destinatario_externo,
            pagina=1,
            x=Decimal("0.1"),
            y=Decimal("0.1"),
            ancho=Decimal("0.2"),
            alto=Decimal("0.1"),
        )

        response = self.client.get(
            reverse("documentos:document_editor", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(DestinatarioDocumento.objects.filter(pk=destinatario_externo.pk).exists())
        self.assertTrue(CampoFirma.objects.filter(pk=campo.pk).exists())

    def test_recargar_editor_conserva_campo_firma(self):
        _, destinatario = self.preparar_envio_con_campo()
        campo = destinatario.campos_firma.get()
        editor_url = reverse("documentos:document_editor", args=[self.documento.pk])

        self.client.get(editor_url)
        self.client.get(editor_url)

        campo.refresh_from_db()
        self.assertEqual(campo.destinatario, destinatario)
        self.assertEqual(campo.pagina, 1)

    def test_post_destinatarios_crea_y_sincroniza_preparacion(self):
        response = self.preparar_destinatarios()
        envio = EnvioDocumento.objects.get(documento=self.documento)
        self.assertRedirects(
            response,
            reverse("documentos:document_editor", args=[self.documento.pk]),
        )
        self.assertTrue(envio.destinatarios.filter(usuario=self.miembro).exists())
        self.assertFalse(envio.destinatarios.filter(usuario=self.inactivo).exists())

        destinatario_externo = DestinatarioDocumento.objects.create(
            envio=envio,
            usuario=self.usuario_externo,
            estado=DestinatarioDocumento.Estado.BORRADOR,
        )

        response = self.preparar_destinatarios()

        self.assertRedirects(
            response,
            reverse("documentos:document_editor", args=[self.documento.pk]),
        )
        self.assertTrue(envio.destinatarios.filter(usuario=self.miembro).exists())
        self.assertFalse(envio.destinatarios.filter(pk=destinatario_externo.pk).exists())

    def test_presidente_no_puede_enviar_documento_ajeno(self):
        ajeno = Documento.objects.create(
            propietario=self.usuario_externo,
            archivo=SimpleUploadedFile("ajeno.pdf", b"%PDF-1.7\najeno"),
            nombre_original="ajeno.pdf",
        )
        self.client.force_login(self.presidente)

        response = self.client.post(reverse("documentos:send", args=[ajeno.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(EnvioDocumento.objects.exists())

    def test_comite_enviado_por_post_es_ignorado(self):
        self.preparar_envio_con_campo()

        self.client.post(
            reverse("documentos:send", args=[self.documento.pk]),
            {"comite": self.otro_comite.pk},
        )

        envio = EnvioDocumento.objects.get()
        self.assertTrue(envio.destinatarios.filter(usuario=self.miembro).exists())
        self.assertFalse(envio.destinatarios.filter(usuario=self.usuario_externo).exists())

    def test_no_se_envia_sin_preparacion_y_campos(self):
        self.client.force_login(self.presidente)

        response = self.client.post(reverse("documentos:send", args=[self.documento.pk]))

        self.assertRedirects(
            response,
            reverse("documentos:committee_recipients", args=[self.documento.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(EnvioDocumento.objects.exists())

    def test_destinatario_ve_pendiente_pero_no_documento_como_propio(self):
        self.crear_envio()
        self.client.force_login(self.miembro)

        pendientes = self.client.get(reverse("documentos:user_pending"))
        propios = self.client.get(reverse("documentos:list"))

        self.assertContains(pendientes, "acta.pdf")
        self.assertNotContains(propios, "acta.pdf")

    def test_usuario_externo_no_ve_pendiente(self):
        self.crear_envio()
        self.client.force_login(self.usuario_externo)

        response = self.client.get(reverse("documentos:user_pending"))

        self.assertNotContains(response, "acta.pdf")

    def test_destinatario_abre_documento_y_cambia_a_visto(self):
        _, destinatario = self.crear_envio()
        self.client.force_login(self.miembro)

        response = self.client.get(
            reverse("documentos:received_document", args=[destinatario.pk])
        )
        contenido = b"".join(response.streaming_content)
        destinatario.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(contenido, b"%PDF-1.7\nacta")
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.VISTO)
        self.assertIsNotNone(destinatario.fecha_visualizacion)

    def test_usuario_no_destinatario_no_puede_abrir_documento(self):
        _, destinatario = self.crear_envio()
        self.client.force_login(self.usuario_externo)

        response = self.client.get(
            reverse("documentos:received_document", args=[destinatario.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_flujo_real_es_privado_para_usuarios_anonimos(self):
        _, destinatario = self.crear_envio()
        rutas = (
            reverse("documentos:committee_recipients", args=[self.documento.pk]),
            reverse("documentos:send_review", args=[self.documento.pk]),
            reverse("documentos:send", args=[self.documento.pk]),
            reverse("documentos:user_pending"),
            reverse("documentos:received_document", args=[destinatario.pk]),
        )

        for ruta in rutas:
            response = self.client.post(ruta) if ruta.endswith("/enviar/") else self.client.get(ruta)
            self.assertEqual(response.status_code, 302)


class EditorPageTests(TestCase):
    def test_editor_page_renders(self):
        response = self.client.get(reverse("documentos:editor"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preparando documento...")
        self.assertContains(response, 'class="field-layer"')
        self.assertContains(response, 'data-field-type="signature"')
        self.assertContains(response, 'data-field-type="name"')
        self.assertContains(response, 'data-field-type="date"')
        self.assertContains(response, 'data-field-type="text"')
        self.assertContains(response, 'data-field-type="initials"')
        self.assertContains(response, 'data-field-type="checkbox"')
        self.assertContains(response, "data-recipient-name")
        self.assertContains(response, "data-properties-content")
        self.assertContains(response, "data-property-required")
        self.assertContains(response, "data-property-label")
        self.assertContains(response, "data-editor-continue")
        self.assertContains(response, f'data-review-url="{reverse("documentos:review")}"')
        self.assertContains(response, "pdf.min.js")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CampoFirmaTests(TestCase):
    def setUp(self):
        self.comite = Comite.objects.create(nombre="Comité campos de firma")
        self.otro_comite = Comite.objects.create(nombre="Comité campos externo")
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        self.propietario = self.crear_usuario("presidente-campos", self.comite, presidente)
        self.destinatario_usuario = self.crear_usuario("destinatario-campos", self.comite, miembro)
        self.no_autorizado = self.crear_usuario("no-autorizado-campos", self.comite, miembro)
        self.otro_presidente = self.crear_usuario("presidente-externo-campos", self.otro_comite, presidente)
        self.otro_destinatario_usuario = self.crear_usuario("destinatario-externo-campos", self.otro_comite, miembro)
        self.documento = self.crear_documento(self.propietario, "campos.pdf", paginas=2)
        self.otro_documento = self.crear_documento(self.otro_presidente, "externo.pdf")

        self.client.force_login(self.propietario)
        self.editor_url = reverse("documentos:document_editor", args=[self.documento.pk])
        self.api_url = reverse("documentos:signature_fields", args=[self.documento.pk])
        self.client.post(
            reverse("documentos:committee_recipients", args=[self.documento.pk])
        )
        self.destinatario = DestinatarioDocumento.objects.get(
            envio__documento=self.documento,
            usuario=self.destinatario_usuario,
        )
        self.destinatario_no_autorizado = DestinatarioDocumento.objects.get(
            envio__documento=self.documento,
            usuario=self.no_autorizado,
        )

        self.client.force_login(self.otro_presidente)
        self.client.post(
            reverse("documentos:committee_recipients", args=[self.otro_documento.pk])
        )
        self.destinatario_externo = DestinatarioDocumento.objects.get(
            envio__documento=self.otro_documento,
            usuario=self.otro_destinatario_usuario,
        )
        self.client.force_login(self.propietario)

    def tearDown(self):
        for documento in (self.documento, self.otro_documento):
            documento.archivo.delete(save=False)

    def crear_usuario(self, nombre, comite, cargo):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name=nombre,
            last_name="Prueba",
            comite=comite,
            cargo=cargo,
        )

    def crear_documento(self, propietario, nombre, paginas=1):
        contenido = BytesIO()
        escritor = PdfWriter()
        for _ in range(paginas):
            escritor.add_blank_page(width=612, height=792)
        escritor.write(contenido)
        return Documento.objects.create(
            propietario=propietario,
            archivo=SimpleUploadedFile(nombre, contenido.getvalue(), content_type="application/pdf"),
            nombre_original=nombre,
        )

    def datos_campo(self, **cambios):
        datos = {
            "id": None,
            "type": "signature",
            "page": 2,
            "x": 0.63,
            "y": 0.71,
            "width": 0.18,
            "height": 0.07,
            "recipient_id": self.destinatario.pk,
        }
        datos.update(cambios)
        return datos

    def guardar(self, campos):
        return self.client.post(
            self.api_url,
            data=json.dumps({"fields": campos}),
            content_type="application/json",
        )

    def datos_para_todos(self):
        return [
            self.datos_campo(),
            self.datos_campo(
                page=1,
                x=0.1,
                y=0.1,
                recipient_id=self.destinatario_no_autorizado.pk,
            ),
        ]

    def test_editor_real_muestra_documento_destinatarios_y_urls_backend(self):
        response = self.client.get(self.editor_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "campos.pdf")
        self.assertContains(response, str(self.destinatario_usuario))
        self.assertContains(response, f'data-fields-url="{self.api_url}"')
        self.assertContains(response, "data-editor-save")
        script_path = finders.find("js/editor.js")
        with open(script_path, encoding="utf-8") as script:
            javascript = script.read()
        self.assertIn("recipientsWithoutSignatureField", javascript)
        self.assertIn("Falta un campo de firma para:", javascript)

    def test_usuario_autorizado_guarda_y_recupera_campo_asociado(self):
        response = self.guardar([self.datos_campo()])

        self.assertEqual(response.status_code, 200)
        campo = CampoFirma.objects.get()
        self.assertEqual(campo.destinatario, self.destinatario)
        self.assertEqual(campo.documento, self.documento)
        self.assertEqual(campo.pagina, 2)
        self.assertEqual(campo.x, Decimal("0.630000"))
        self.assertEqual(campo.y, Decimal("0.710000"))
        self.assertEqual(campo.ancho, Decimal("0.180000"))
        self.assertEqual(campo.alto, Decimal("0.070000"))

        recuperados = self.client.get(self.api_url).json()["fields"]
        self.assertEqual(len(recuperados), 1)
        self.assertEqual(recuperados[0]["recipient_id"], self.destinatario.pk)
        self.assertEqual(recuperados[0]["page"], 2)

    def test_campo_existente_se_actualiza_sin_duplicarse(self):
        campo_id = self.guardar([self.datos_campo()]).json()["fields"][0]["id"]

        response = self.guardar([self.datos_campo(id=campo_id, x=0.1, width=0.25)])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CampoFirma.objects.count(), 1)
        campo = CampoFirma.objects.get()
        self.assertEqual(campo.x, Decimal("0.100000"))
        self.assertEqual(campo.ancho, Decimal("0.250000"))

    def test_un_destinatario_no_admite_dos_campos(self):
        response = self.guardar([self.datos_campo(), self.datos_campo(x=0.2)])

        self.assertEqual(response.status_code, 400)
        self.assertIn("un solo campo", response.json()["error"])
        self.assertEqual(CampoFirma.objects.count(), 0)

        self.guardar([self.datos_campo()])

        with self.assertRaises(IntegrityError), transaction.atomic():
            CampoFirma.objects.create(
                destinatario=self.destinatario,
                pagina=1,
                x=Decimal("0.1"),
                y=Decimal("0.1"),
                ancho=Decimal("0.2"),
                alto=Decimal("0.1"),
            )

    def test_campo_omitido_se_elimina(self):
        self.guardar([self.datos_campo()])

        response = self.guardar([])

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CampoFirma.objects.exists())

    def test_usuario_no_autorizado_no_puede_consultar_ni_modificar(self):
        self.client.force_login(self.no_autorizado)

        self.assertEqual(self.client.get(self.api_url).status_code, 403)
        self.assertEqual(self.guardar([self.datos_campo()]).status_code, 403)
        self.assertFalse(CampoFirma.objects.exists())

        self.client.force_login(self.otro_presidente)
        self.assertEqual(self.client.get(self.editor_url).status_code, 404)
        self.assertEqual(self.client.get(self.api_url).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("documentos:download", args=[self.documento.pk])).status_code,
            404,
        )

    def test_usuario_anonimo_debe_autenticarse(self):
        self.client.logout()

        response = self.client.get(self.api_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("usuarios:login"), response.url)

    def test_rechaza_destinatario_de_otro_documento(self):
        response = self.guardar([
            self.datos_campo(recipient_id=self.destinatario_externo.pk)
        ])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(CampoFirma.objects.exists())

    def test_rechaza_coordenadas_dimensiones_y_paginas_invalidas(self):
        casos = (
            {"x": -0.01},
            {"y": 1.01},
            {"width": 0},
            {"height": 1.01},
            {"x": 0.9, "width": 0.2},
            {"y": 0.95, "height": 0.1},
            {"page": 0},
            {"page": 3},
        )
        for cambios in casos:
            with self.subTest(cambios=cambios):
                response = self.guardar([self.datos_campo(**cambios)])
                self.assertEqual(response.status_code, 400)
                self.assertFalse(CampoFirma.objects.exists())

    def test_rechaza_strings_booleanos_y_valores_no_finitos(self):
        casos = (
            {"x": "0.1"},
            {"y": True},
            {"width": None},
            {"height": float("nan")},
            {"x": float("inf")},
            {"y": float("-inf")},
        )
        for cambios in casos:
            with self.subTest(cambios=cambios):
                response = self.guardar([self.datos_campo(**cambios)])
                self.assertEqual(response.status_code, 400)
                self.assertFalse(CampoFirma.objects.exists())

    def test_pdf_corrupto_devuelve_error_controlado(self):
        self.documento.archivo.delete(save=False)
        self.documento.archivo = SimpleUploadedFile(
            "corrupto.pdf", b"%PDF-1.7\ncorrupto", content_type="application/pdf"
        )
        self.documento.save()

        response = self.guardar([self.datos_campo(page=1)])

        self.assertEqual(response.status_code, 422)
        self.assertIn("número de páginas", response.json()["error"])
        self.assertFalse(CampoFirma.objects.exists())

    def test_destinatarios_en_preparacion_no_aparecen_en_bandeja(self):
        self.client.force_login(self.destinatario_usuario)

        response = self.client.get(reverse("documentos:user_pending"))

        self.assertNotContains(response, "campos.pdf")
        self.assertEqual(
            self.client.get(
                reverse("documentos:received_document", args=[self.destinatario.pk])
            ).status_code,
            404,
        )

    def test_confirmar_envio_publica_destinatarios_y_conserva_campos(self):
        self.guardar(self.datos_para_todos())

        response = self.client.post(reverse("documentos:send", args=[self.documento.pk]))

        self.assertRedirects(
            response,
            reverse("documentos:document_detail", args=[self.documento.pk]),
        )
        self.destinatario.refresh_from_db()
        self.assertEqual(self.destinatario.envio.estado, EnvioDocumento.Estado.ENVIADO)
        self.assertEqual(self.destinatario.estado, DestinatarioDocumento.Estado.PENDIENTE)
        self.assertEqual(self.destinatario.campos_firma.count(), 1)
        self.assertEqual(CampoFirma.objects.count(), 2)

        self.client.force_login(self.destinatario_usuario)
        self.assertContains(self.client.get(reverse("documentos:user_pending")), "campos.pdf")

    def test_falta_de_campo_mantiene_envio_y_destinatarios_en_borrador(self):
        segundo_usuario = self.crear_usuario(
            "segundo-destinatario", self.comite, self.destinatario_usuario.cargo
        )
        self.client.post(
            reverse("documentos:committee_recipients", args=[self.documento.pk])
        )
        self.guardar(self.datos_para_todos())

        response = self.client.post(
            reverse("documentos:send", args=[self.documento.pk]),
            follow=True,
        )

        envio = EnvioDocumento.objects.get(documento=self.documento)
        segundo = envio.destinatarios.get(usuario=segundo_usuario)
        self.destinatario.refresh_from_db()
        self.assertContains(response, str(segundo_usuario))
        self.assertEqual(envio.estado, EnvioDocumento.Estado.PREPARACION)
        self.assertEqual(self.destinatario.estado, DestinatarioDocumento.Estado.BORRADOR)
        self.assertEqual(segundo.estado, DestinatarioDocumento.Estado.BORRADOR)

    def test_campos_no_se_modifican_despues_del_envio(self):
        campo_id = self.guardar(self.datos_para_todos()).json()["fields"][0]["id"]
        self.client.post(reverse("documentos:send", args=[self.documento.pk]))

        self.assertEqual(self.client.get(self.editor_url).status_code, 403)
        self.assertEqual(self.client.get(self.api_url).status_code, 404)
        response = self.guardar([self.datos_campo(id=campo_id, x=0.2)])

        self.assertEqual(response.status_code, 404)
        self.assertEqual(CampoFirma.objects.get(pk=campo_id).x, Decimal("0.630000"))

    def test_estados_finales_incluyen_firmado_y_borrador(self):
        self.assertIn(EnvioDocumento.Estado.PREPARACION, EnvioDocumento.Estado.values)
        self.assertIn(EnvioDocumento.Estado.ENVIADO, EnvioDocumento.Estado.values)
        self.assertEqual(
            DestinatarioDocumento.Estado.values,
            ["BORRADOR", "PENDIENTE", "VISTO", "FIRMADO"],
        )


class RecipientExperienceTests(TestCase):
    def test_request_page_has_simplified_entry(self):
        response = self.client.get(reverse("firmas:request"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "te ha solicitado revisar y firmar")
        self.assertNotContains(response, "Navegación principal")

    def test_sign_page_has_fields_canvas_and_consent(self):
        response = self.client.get(reverse("firmas:sign"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-signature-canvas')
        self.assertContains(response, 'data-completable="signature"')
        self.assertContains(response, "pdf.min.js")
        self.assertContains(response, "Rechazar")
        self.assertContains(response, "Confirmo que he revisado el documento")
        self.assertContains(response, "Finalizar firma")

    def test_completed_page_renders(self):
        response = self.client.get(reverse("firmas:completed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Documento completado")
        self.assertContains(response, "Tu firma se registró correctamente")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UserDocumentPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité portal destinatario")
        otro_comite = Comite.objects.create(nombre="Comité portal externo")
        cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        cls.user = get_user_model().objects.create_user(
            email="destinatario@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Bryan",
            last_name="López",
            comite=comite,
            cargo=cargo,
        )
        cls.other_user = get_user_model().objects.create_user(
            email="otro-destinatario@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Otro",
            last_name="Usuario",
            comite=otro_comite,
            cargo=cargo,
        )
        cls.sender = get_user_model().objects.create_user(
            email="remitente-portal@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Ana",
            last_name="Remitente",
            comite=comite,
            cargo=presidente,
        )
        cls.pending = cls.create_recipient("Pendiente real.pdf", cls.user)
        cls.viewed = cls.create_recipient(
            "Documento visto.pdf",
            cls.user,
            DestinatarioDocumento.Estado.VISTO,
        )
        cls.completed = cls.create_recipient(
            "Documento firmado.pdf",
            cls.user,
            DestinatarioDocumento.Estado.FIRMADO,
        )
        cls.foreign = cls.create_recipient("Documento ajeno.pdf", cls.other_user)

    @classmethod
    def create_recipient(cls, name, user, status=DestinatarioDocumento.Estado.PENDIENTE):
        document = Documento.objects.create(
            propietario=cls.sender,
            archivo=SimpleUploadedFile(name, b"%PDF-1.7\nportal"),
            nombre_original=name,
        )
        shipment = EnvioDocumento.objects.create(
            documento=document,
            remitente=cls.sender,
        )
        return DestinatarioDocumento.objects.create(
            envio=shipment,
            usuario=user,
            estado=status,
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_authenticated_user_can_open_dashboard(self):
        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "documentos/user_dashboard.html")
        self.assertContains(response, "Hola, Bryan")
        self.assertEqual(response.context["document_count"], 3)
        self.assertEqual(response.context["pending_count"], 2)
        self.assertEqual(response.context["completed_count"], 1)
        self.assertContains(response, "Pendiente real.pdf")
        self.assertContains(response, "Documento visto.pdf")
        self.assertNotContains(response, "Documento ajeno.pdf")

    def test_anonymous_user_is_redirected_from_documents(self):
        self.client.logout()

        response = self.client.get(reverse("documentos:user_documents"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("usuarios:login"), response.url)

    def test_portal_only_shows_documents_assigned_to_user(self):
        response = self.client.get(reverse("documentos:user_documents"))

        self.assertEqual(response.context["document_count"], 3)
        self.assertContains(response, "Pendiente real.pdf")
        self.assertContains(response, "Documento visto.pdf")
        self.assertContains(response, "Documento firmado.pdf")
        self.assertNotContains(response, "Documento ajeno.pdf")

    def test_pending_filter_uses_pending_status(self):
        response = self.client.get(reverse("documentos:user_pending"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], "pendientes")
        self.assertContains(response, "Pendiente real.pdf")
        self.assertContains(response, "Documento visto.pdf")
        self.assertNotContains(response, "Documento firmado.pdf")

    def test_legacy_pending_page_excludes_completed_documents(self):
        response = self.client.get(reverse("documentos:pending"))

        self.assertRedirects(response, reverse("documentos:user_pending"))

    def test_completed_filter_uses_completed_status(self):
        response = self.client.get(reverse("documentos:user_completed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], "completados")
        self.assertContains(response, "Documento firmado.pdf")
        self.assertNotContains(response, "Pendiente real.pdf")
        self.assertNotContains(response, "Documento visto.pdf")

    def test_invalid_filter_falls_back_to_all(self):
        response = self.client.get(
            reverse("documentos:user_documents"),
            {"estado": "inventado"},
        )

        self.assertEqual(response.context["selected_status"], "todos")

    def test_rows_use_real_review_and_view_endpoints(self):
        response = self.client.get(reverse("documentos:user_documents"))

        self.assertContains(
            response,
            reverse("firmas:recipient_sign", args=[self.pending.pk]),
        )
        self.assertContains(
            response,
            reverse("documentos:received_document", args=[self.completed.pk]),
        )

    def test_user_with_sender_role_can_also_open_recipient_portal(self):
        self.client.force_login(self.sender)

        response = self.client.get(reverse("documentos:user_documents"))

        self.assertEqual(response.status_code, 200)

    def test_sender_dashboard_and_document_flow_still_work(self):
        self.client.force_login(self.sender)

        response = self.client.get(reverse("usuarios:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nuevo documento")


class DocumentoResultadoTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.comite = Comite.objects.create(nombre="Comite resultado")
        self.otro_comite = Comite.objects.create(nombre="Comite resultado externo")
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        self.propietario = self._usuario("resultado-presidente", self.comite, presidente)
        self.usuario_a = self._usuario("resultado-a", self.comite, miembro)
        self.usuario_b = self._usuario("resultado-b", self.comite, miembro)
        self.no_relacionado = self._usuario("resultado-no", self.comite, miembro)
        self.externo = self._usuario("resultado-externo", self.otro_comite, miembro)

    def _usuario(self, nombre, comite, cargo):
        return get_user_model().objects.create_user(
            email=f"{nombre}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name=nombre,
            comite=comite,
            cargo=cargo,
        )

    def _pdf(self, sizes=((612, 792),), rotations=None):
        output = BytesIO()
        writer = PdfWriter()
        rotations = rotations or [0] * len(sizes)
        for size, rotation in zip(sizes, rotations):
            page = writer.add_blank_page(width=size[0], height=size[1])
            if rotation:
                page.rotate(rotation)
        writer.write(output)
        return output.getvalue()

    def _image(self, image_format="PNG", size=(120, 40), transparent=False):
        output = BytesIO()
        if image_format == "JPEG":
            image = Image.new("RGB", size, (18, 53, 110))
        else:
            image = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (18, 53, 110, 255))
            if transparent:
                for x in range(size[0]):
                    image.putpixel((x, min(size[1] - 1, x * size[1] // size[0])), (18, 53, 110, 255))
        image.save(output, image_format)
        return output.getvalue()

    def _crear_envio(self, sizes=((612, 792),), rotations=None, estado=EnvioDocumento.Estado.ENVIADO):
        original = self._pdf(sizes, rotations)
        documento = Documento.objects.create(
            propietario=self.propietario,
            archivo=SimpleUploadedFile("Acta reunion.pdf", original, content_type="application/pdf"),
            nombre_original="Acta reunion.pdf",
        )
        envio = EnvioDocumento.objects.create(
            documento=documento,
            remitente=self.propietario,
            estado=estado,
        )
        return envio, original

    def _agregar_firmante(
        self,
        envio,
        usuario,
        pagina=1,
        estado=DestinatarioDocumento.Estado.FIRMADO,
        formato="image/png",
        image_format="PNG",
        image_size=(120, 40),
        transparent=False,
        campo=True,
        firma=True,
        x="0.10",
        y="0.20",
        ancho="0.30",
        alto="0.10",
        metodo=Firma.Metodo.DIBUJADA,
    ):
        destinatario = DestinatarioDocumento.objects.create(
            envio=envio,
            usuario=usuario,
            estado=estado,
        )
        if campo:
            CampoFirma.objects.create(
                destinatario=destinatario,
                pagina=pagina,
                x=Decimal(x),
                y=Decimal(y),
                ancho=Decimal(ancho),
                alto=Decimal(alto),
            )
        if firma:
            Firma.objects.create(
                destinatario=destinatario,
                imagen=self._image(image_format, image_size, transparent),
                formato=formato,
                metodo=metodo,
                consentimiento=True,
            )
        return destinatario

    def _resultado_bytes(self, resultado):
        with resultado.archivo.open("rb") as archivo:
            return archivo.read()

    def _image_objects(self, page):
        return list(page.images)

    def _drawn_image_count(self, page):
        return sum(1 for _, operator in page.get_contents().operations if operator == b"Do")

    def test_no_genera_si_falta_una_firma_y_detecta_envio_incompleto(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        self._agregar_firmante(
            envio,
            self.usuario_b,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
            firma=False,
        )

        self.assertFalse(envio_esta_completo(envio))
        self.assertIsNone(generar_resultado_si_completo(envio.pk))
        self.assertFalse(DocumentoResultado.objects.exists())

    def test_genera_unico_resultado_idempotente_despues_de_ultima_firma(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)

        primero = generar_resultado_si_completo(envio.pk)
        segundo = generar_resultado_si_completo(envio.pk)

        self.assertTrue(envio_esta_completo(envio))
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(DocumentoResultado.objects.count(), 1)
        self.assertEqual(
            len(list(Path(self.media_root).glob("documentos_resultados/**/*.pdf"))),
            1,
        )

    def test_original_permanece_intacto_y_hashes_corresponden(self):
        envio, original = self._crear_envio()
        original_name = envio.documento.archivo.name
        original_hash = envio.documento.hash_sha256
        self._agregar_firmante(envio, self.usuario_a)

        resultado = generar_resultado_si_completo(envio.pk)
        result_bytes = self._resultado_bytes(resultado)
        envio.documento.refresh_from_db()
        with envio.documento.archivo.open("rb") as archivo:
            persisted_original = archivo.read()

        self.assertEqual(envio.documento.archivo.name, original_name)
        self.assertEqual(persisted_original, original)
        self.assertEqual(envio.documento.hash_sha256, original_hash)
        self.assertEqual(original_hash, hashlib.sha256(original).hexdigest())
        self.assertEqual(resultado.hash_sha256, hashlib.sha256(result_bytes).hexdigest())
        self.assertEqual(resultado.tamano, len(result_bytes))
        self.assertNotEqual(resultado.archivo.name, original_name)

    def test_hash_original_inconsistente_impide_generacion(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        Documento.objects.filter(pk=envio.documento_id).update(hash_sha256="0" * 64)

        with self.assertRaisesRegex(ResultadoPDFError, "hash registrado"):
            generar_resultado_si_completo(envio.pk)

        self.assertFalse(DocumentoResultado.objects.exists())

    def test_resultado_es_pdf_valido_y_conserva_paginas_originales(self):
        envio, _ = self._crear_envio(sizes=((612, 792), (595, 842), (792, 612)))
        self._agregar_firmante(envio, self.usuario_a, pagina=1)
        self._agregar_firmante(envio, self.usuario_b, pagina=3)

        reader = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk))))

        self.assertEqual(len(reader.pages), 3)
        self.assertEqual(len(self._image_objects(reader.pages[0])), 1)
        self.assertEqual(len(self._image_objects(reader.pages[1])), 0)
        self.assertEqual(len(self._image_objects(reader.pages[2])), 1)

    def test_dos_firmas_en_misma_pagina_crean_dos_imagenes(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, x="0.1")
        self._agregar_firmante(envio, self.usuario_b, x="0.6")

        reader = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk))))

        # ReportLab reutiliza un solo XObject cuando los bytes coinciden, pero lo dibuja dos veces.
        self.assertEqual(self._drawn_image_count(reader.pages[0]), 2)

    def test_convierte_x_y_ancho_alto_con_origen_superior_izquierdo(self):
        envio, _ = self._crear_envio()
        destinatario = self._agregar_firmante(
            envio, self.usuario_a, x="0.25", y="0.20", ancho="0.50", alto="0.10"
        )
        campo = destinatario.campos_firma.get()

        self.assertEqual(calcular_rectangulo_pdf(campo, 600, 800), (150, 560, 300, 80))
        self.assertEqual(
            calcular_rectangulo_pdf(campo, 600, 800, left=10, bottom=20),
            (160, 580, 300, 80),
        )

    def test_aspect_ratio_se_conserva_y_firma_se_centra(self):
        x, y, width, height = calcular_colocacion_firma((10, 20, 200, 100), 400, 100)

        self.assertEqual((x, y, width, height), (10, 45, 200, 50))
        self.assertEqual(width / height, 4)

    def test_png_dibujado_png_perfil_y_jpeg_perfil_funcionan_juntos(self):
        envio, _ = self._crear_envio(sizes=((612, 792), (612, 792), (612, 792)))
        self._agregar_firmante(envio, self.usuario_a, pagina=1, metodo=Firma.Metodo.DIBUJADA)
        self._agregar_firmante(
            envio,
            self.usuario_b,
            pagina=3,
            formato="image/jpeg",
            image_format="JPEG",
            metodo=Firma.Metodo.PERFIL,
        )

        reader = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk))))

        self.assertEqual(len(self._image_objects(reader.pages[0])), 1)
        self.assertEqual(len(self._image_objects(reader.pages[2])), 1)

    def test_png_transparente_genera_mascara_alfa(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, transparent=True)

        reader = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk))))
        images = self._image_objects(reader.pages[0])

        self.assertEqual(len(images), 1)
        self.assertIn("/SMask", images[0].indirect_reference.get_object())

    def test_letter_a4_y_paginas_de_tamanos_diferentes(self):
        sizes = ((612, 792), (595, 842), (842, 595))
        envio, _ = self._crear_envio(sizes=sizes)
        self._agregar_firmante(envio, self.usuario_a, pagina=1)
        self._agregar_firmante(envio, self.usuario_b, pagina=3)

        reader = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk))))

        self.assertEqual(
            [(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages],
            list(sizes),
        )

    def test_rotacion_se_transfiere_al_contenido_antes_de_firmar(self):
        envio, _ = self._crear_envio(sizes=((612, 792),), rotations=(90,))
        self._agregar_firmante(envio, self.usuario_a)

        page = PdfReader(BytesIO(self._resultado_bytes(generar_resultado_si_completo(envio.pk)))).pages[0]

        self.assertEqual(page.rotation, 0)
        self.assertEqual((float(page.mediabox.width), float(page.mediabox.height)), (792, 612))
        self.assertEqual(len(self._image_objects(page)), 1)

    def test_pagina_inexistente_impide_generacion(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, pagina=2)

        with self.assertRaisesRegex(ResultadoPDFError, "página inexistente"):
            generar_resultado_si_completo(envio.pk)
        self.assertFalse(DocumentoResultado.objects.exists())

    def test_campo_faltante_impide_generacion(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, campo=False)

        with self.assertRaisesRegex(ResultadoPDFError, "exactamente un campo"):
            generar_resultado_si_completo(envio.pk)
        self.assertFalse(DocumentoResultado.objects.exists())

    def test_firma_faltante_impide_generacion_aunque_estado_sea_firmado(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, firma=False)

        with self.assertRaisesRegex(ResultadoPDFError, "exactamente una firma"):
            generar_resultado_si_completo(envio.pk)

    def test_formato_no_soportado_impide_generacion(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a, formato="image/gif")

        with self.assertRaisesRegex(ResultadoPDFError, "formato no soportado"):
            generar_resultado_si_completo(envio.pk)

    def test_envio_no_enviado_impide_generacion(self):
        envio, _ = self._crear_envio(estado=EnvioDocumento.Estado.PREPARACION)
        self._agregar_firmante(envio, self.usuario_a)

        with self.assertRaisesRegex(ResultadoPDFError, "no está en estado ENVIADO"):
            construir_pdf_resultado(envio)

    def test_pdf_corrupto_falla_sin_resultado_parcial(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        envio.documento.archivo.delete(save=False)
        envio.documento.archivo = SimpleUploadedFile("corrupto.pdf", b"%PDF-1.7\ncorrupto")
        envio.documento.save()

        with self.assertRaises(ResultadoPDFError):
            generar_resultado_si_completo(envio.pk)
        self.assertFalse(DocumentoResultado.objects.exists())

    def test_fallo_de_base_de_datos_limpia_archivo_resultante(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)

        with patch.object(DocumentoResultado, "save", side_effect=RuntimeError("fallo")):
            with self.assertRaisesRegex(ResultadoPDFError, "guardar"):
                generar_resultado_si_completo(envio.pk)

        self.assertFalse(DocumentoResultado.objects.exists())
        self.assertEqual(list(Path(self.media_root).glob("documentos_resultados/**/*.pdf")), [])

    def test_descarga_protegida_para_propietario_y_destinatario_firmado(self):
        envio, _ = self._crear_envio()
        destinatario = self._agregar_firmante(envio, self.usuario_a)
        generar_resultado_si_completo(envio.pk)
        url = reverse("documentos:download_result", args=[envio.pk])

        for usuario in (self.propietario, self.usuario_a):
            self.client.force_login(usuario)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn("acta-reunion_firmado.pdf", response["Content-Disposition"])
            self.assertIn("private", response["Cache-Control"])
            self.assertIn("no-store", response["Cache-Control"])
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.FIRMADO)

    def test_usuarios_no_relacionados_y_otro_comite_reciben_404(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        generar_resultado_si_completo(envio.pk)
        url = reverse("documentos:download_result", args=[envio.pk])

        for usuario in (self.no_relacionado, self.externo):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_antes_de_completarse_no_hay_descarga(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(
            envio,
            self.usuario_a,
            estado=DestinatarioDocumento.Estado.PENDIENTE,
            firma=False,
        )
        self.client.force_login(self.propietario)

        self.assertEqual(
            self.client.get(reverse("documentos:download_result", args=[envio.pk])).status_code,
            404,
        )

    def test_descarga_de_resultado_requiere_autenticacion(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        generar_resultado_si_completo(envio.pk)

        response = self.client.get(reverse("documentos:download_result", args=[envio.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("usuarios:login"), response.url)

    def test_firma_perfil_reemplazada_o_eliminada_no_afecta_generacion(self):
        envio, _ = self._crear_envio()
        original = self._image("PNG")
        perfil = FirmaPerfil.objects.create(
            usuario=self.usuario_a, imagen=original, formato="image/png"
        )
        destinatario = self._agregar_firmante(
            envio, self.usuario_a, metodo=Firma.Metodo.PERFIL
        )
        firma = destinatario.firma
        firma.imagen = bytes(perfil.imagen)
        firma.save(update_fields=("imagen",))
        perfil.imagen = self._image("JPEG")
        perfil.formato = "image/jpeg"
        perfil.save(update_fields=("imagen", "formato"))
        perfil.delete()

        resultado = generar_resultado_si_completo(envio.pk)

        self.assertTrue(resultado.archivo)
        firma.refresh_from_db()
        self.assertEqual(bytes(firma.imagen), original)

    def test_detalle_muestra_conteo_y_disponibilidad_minima(self):
        envio, _ = self._crear_envio()
        self._agregar_firmante(envio, self.usuario_a)
        self.client.force_login(self.propietario)
        url = reverse("documentos:document_detail", args=[envio.documento_id])

        with patch(
            "documentos.view.generar_resultado_si_completo",
            side_effect=ResultadoPDFError("fallo transitorio"),
        ):
            pendiente = self.client.get(url)
        self.assertContains(pendiente, "1 de 1 firmados")
        self.assertContains(pendiente, "Documento firmado aún no disponible")

        completo = self.client.get(url)
        self.assertContains(completo, "Descargar documento firmado")
        self.assertNotContains(completo, "Documento firmado aún no disponible")
