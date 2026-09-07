import hashlib
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from usuarios.models import Cargo, Comite

from .models import DestinatarioDocumento, Documento, EnvioDocumento


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

        self.assertContains(response, f'href="{reverse("documentos:list")}"', count=2)
        self.assertContains(response, f'data-editor-url="{reverse("documentos:recipients")}"')

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

    def test_presidente_envia_documento_a_integrantes_activos_sin_incluirse(self):
        self.client.force_login(self.presidente)
        response = self.client.post(reverse("documentos:send", args=[self.documento.pk]))

        self.assertRedirects(response, reverse("documentos:list"))
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
        self.client.force_login(self.presidente)

        for nombre_ruta in ("committee_recipients", "send_review"):
            response = self.client.get(
                reverse(f"documentos:{nombre_ruta}", args=[self.documento.pk])
            )
            self.assertContains(response, "acta.pdf")
            self.assertContains(response, self.comite.nombre)
            self.assertContains(response, str(self.miembro))
            self.assertNotContains(response, str(self.inactivo))
            self.assertNotContains(response, str(self.usuario_externo))

    def test_restriccion_impide_destinatario_duplicado_en_un_envio(self):
        envio, _ = self.crear_envio()

        with self.assertRaises(IntegrityError), transaction.atomic():
            DestinatarioDocumento.objects.create(envio=envio, usuario=self.miembro)

    def test_doble_confirmacion_no_duplica_envio_ni_destinatarios(self):
        self.client.force_login(self.presidente)
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
        self.client.force_login(self.presidente)

        self.client.post(
            reverse("documentos:send", args=[self.documento.pk]),
            {"comite": self.otro_comite.pk},
        )

        envio = EnvioDocumento.objects.get()
        self.assertTrue(envio.destinatarios.filter(usuario=self.miembro).exists())
        self.assertFalse(envio.destinatarios.filter(usuario=self.usuario_externo).exists())

    def test_destinatario_ve_pendiente_pero_no_documento_como_propio(self):
        self.crear_envio()
        self.client.force_login(self.miembro)

        pendientes = self.client.get(reverse("documentos:pending"))
        propios = self.client.get(reverse("documentos:list"))

        self.assertContains(pendientes, "acta.pdf")
        self.assertNotContains(propios, "acta.pdf")

    def test_usuario_externo_no_ve_pendiente(self):
        self.crear_envio()
        self.client.force_login(self.usuario_externo)

        response = self.client.get(reverse("documentos:pending"))

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
            reverse("documentos:pending"),
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
