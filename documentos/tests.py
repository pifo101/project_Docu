import hashlib
import json
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from usuarios.models import Cargo, Comite

from .models import CampoFirma, DestinatarioDocumento, Documento, EnvioDocumento


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

    def preparar_envio_con_campo(self):
        self.client.force_login(self.presidente)
        self.client.get(reverse("documentos:document_editor", args=[self.documento.pk]))
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

        response = self.client.get(
            reverse("documentos:document_editor", args=[self.documento.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(EnvioDocumento.objects.exists())

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
            reverse("documentos:document_editor", args=[self.documento.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(EnvioDocumento.objects.exists())

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
        self.client.get(self.editor_url)
        self.destinatario = DestinatarioDocumento.objects.get(
            envio__documento=self.documento,
            usuario=self.destinatario_usuario,
        )
        self.destinatario_no_autorizado = DestinatarioDocumento.objects.get(
            envio__documento=self.documento,
            usuario=self.no_autorizado,
        )

        self.client.force_login(self.otro_presidente)
        self.client.get(reverse("documentos:document_editor", args=[self.otro_documento.pk]))
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

        response = self.client.get(reverse("documentos:pending"))

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

        self.assertRedirects(response, reverse("documentos:list"))
        self.destinatario.refresh_from_db()
        self.assertEqual(self.destinatario.envio.estado, EnvioDocumento.Estado.ENVIADO)
        self.assertEqual(self.destinatario.estado, DestinatarioDocumento.Estado.PENDIENTE)
        self.assertEqual(self.destinatario.campos_firma.count(), 1)
        self.assertEqual(CampoFirma.objects.count(), 2)

        self.client.force_login(self.destinatario_usuario)
        self.assertContains(self.client.get(reverse("documentos:pending")), "campos.pdf")

    def test_falta_de_campo_mantiene_envio_y_destinatarios_en_borrador(self):
        segundo_usuario = self.crear_usuario(
            "segundo-destinatario", self.comite, self.destinatario_usuario.cargo
        )
        self.client.get(self.editor_url)
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
