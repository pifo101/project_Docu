import hashlib
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from usuarios.models import Cargo, Comite

from .models import Documento


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

    def test_pending_page_renders_documents_and_empty_state(self):
        response = self.client.get(reverse("documentos:pending"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pendientes de firma")
        self.assertContains(response, "No tienes documentos pendientes de firma")


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
