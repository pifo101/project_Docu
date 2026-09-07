from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from usuarios.models import Cargo, Comite


class StaffPageMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        comite = Comite.objects.create(nombre=f"Comité {cls.__name__}")
        cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.staff_user = get_user_model().objects.create_user(
            email=f"{cls.__name__.lower()}@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Andrea",
            last_name="Morales",
            comite=comite,
            cargo=cargo,
            is_staff=True,
        )

    def setUp(self):
        self.client.force_login(self.staff_user)


class DocumentsPageTests(StaffPageMixin, TestCase):
    def test_documents_page_renders_mock_list_and_controls(self):
        response = self.client.get(reverse("documentos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mis documentos")
        self.assertContains(response, "Contrato de servicios 2026")
        self.assertContains(response, 'data-document-search')
        self.assertContains(response, 'data-filter="expired"')
        self.assertContains(response, 'data-empty-state')
        self.assertContains(response, 'data-upload-open', count=3)

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


class EditorPageTests(StaffPageMixin, TestCase):
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


class RecipientExperienceTests(StaffPageMixin, TestCase):
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


class UserDocumentPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité portal destinatario")
        cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.user = get_user_model().objects.create_user(
            email="destinatario@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Bryan",
            last_name="López",
            comite=comite,
            cargo=cargo,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_authenticated_user_can_open_dashboard(self):
        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "documentos/user_dashboard.html")
        self.assertContains(response, "Hola, Bryan")
        self.assertContains(response, "No tienes documentos pendientes")

    def test_anonymous_user_is_redirected_from_documents(self):
        self.client.logout()

        response = self.client.get(reverse("documentos:user_documents"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("usuarios:login"), response.url)

    def test_portal_does_not_show_mock_documents(self):
        response = self.client.get(reverse("documentos:user_documents"))

        self.assertEqual(response.context["documents"], ())
        self.assertEqual(response.context["document_count"], 0)
        self.assertNotContains(response, "Contrato de servicios 2026")
        self.assertContains(response, "Aún no tienes documentos asignados")

    def test_pending_filter_uses_pending_status(self):
        response = self.client.get(reverse("documentos:user_pending"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], "pendientes")
        self.assertContains(response, "No tienes documentos pendientes")

    def test_completed_filter_uses_completed_status(self):
        response = self.client.get(reverse("documentos:user_completed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], "completados")
        self.assertContains(response, "Aún no tienes documentos completados")

    def test_invalid_filter_falls_back_to_all(self):
        response = self.client.get(
            reverse("documentos:user_documents"),
            {"estado": "inventado"},
        )

        self.assertEqual(response.context["selected_status"], "todos")

    def test_normal_user_cannot_open_sender_pages(self):
        protected_urls = (
            "documentos:list",
            "documentos:pending",
            "documentos:detail",
            "documentos:recipients",
            "documentos:editor",
            "documentos:review",
            "firmas:request",
            "firmas:sign",
            "firmas:completed",
        )

        for url_name in protected_urls:
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 403)

    def test_administrative_page_still_works_for_staff(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.get(reverse("documentos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nuevo documento")
