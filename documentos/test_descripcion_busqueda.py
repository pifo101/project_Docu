import base64
import hashlib
import json
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from usuarios.models import Cargo, Comite
from .models import CampoFirma, DestinatarioDocumento, Documento, DocumentoResultado, EnvioDocumento


class DescripcionBusquedaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité descripción")
        cls.presidente = get_user_model().objects.create_user(
            email="descripcion@adicla.org.gt", first_name="Ana", last_name="Prueba",
            comite=comite, cargo_id=Cargo.Codigo.PRESIDENTE,
        )
        cls.otro = get_user_model().objects.create_user(
            email="otro-descripcion@adicla.org.gt", first_name="Otro",
            comite=Comite.objects.create(nombre="Comité privado"), cargo_id=Cargo.Codigo.PRESIDENTE,
        )

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.client.force_login(self.presidente)

    def pdf(self, nombre="Acta reunión septiembre.pdf"):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(output)
        return SimpleUploadedFile(nombre, output.getvalue(), content_type="application/pdf")

    def documento(self, propietario=None, nombre="Acta reunión septiembre.pdf", **kwargs):
        return Documento.objects.create(
            propietario=propietario or self.presidente,
            archivo=self.pdf(nombre), nombre_original=nombre, **kwargs,
        )

    def buscar(self, query=None, **kwargs):
        if query is not None:
            kwargs["q"] = query
        return self.client.get(reverse("documentos:list"), kwargs)

    def test_carga_sin_descripcion(self):
        response = self.client.post(reverse("documentos:upload"), {"archivo": self.pdf()})
        self.assertRedirects(response, reverse("documentos:list"))
        self.assertEqual(Documento.objects.get().descripcion, "")

    def test_carga_persiste_descripcion_y_propietario_autenticado(self):
        texto = "Acta mensual del comité de comunicación\nAcuerdos y seguimiento."
        response = self.client.post(reverse("documentos:upload"), {
            "archivo": self.pdf(), "descripcion": texto, "propietario": self.otro.pk,
        })
        self.assertRedirects(response, reverse("documentos:list"))
        documento = Documento.objects.get()
        self.assertEqual(documento.descripcion, texto)
        self.assertEqual(documento.propietario, self.presidente)
        self.assertContains(self.client.get(reverse("documentos:document_detail", args=[documento.pk])), texto)

    def test_limite_backend_y_conservacion_de_errores(self):
        response = self.client.post(reverse("documentos:upload"), {
            "archivo": self.pdf(), "descripcion": "a" * 1001,
        })
        error = response.context["form"].errors.as_data()["descripcion"][0]
        self.assertEqual(error.code, "max_length")
        self.assertFalse(Documento.objects.exists())
        self.assertContains(response, "a" * 1001)
        self.assertContains(response, "data-upload-initial-open")

    def test_acepta_limite_exacto(self):
        response = self.client.post(reverse("documentos:upload"), {
            "archivo": self.pdf(), "descripcion": "á" * 1000,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Documento.objects.get().descripcion, "á" * 1000)

    def test_descripcion_es_texto_escapado_en_detalle(self):
        documento = self.documento(descripcion='<script>alert("hola")</script>')
        response = self.client.get(reverse("documentos:document_detail", args=[documento.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("hola")</script>')

    def test_formulario_disponible_en_dashboard_listado_y_carga(self):
        for route in ("usuarios:dashboard", "documentos:list", "documentos:upload"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertContains(response, 'name="descripcion"')
                self.assertContains(response, 'maxlength="1000"')
                self.assertContains(response, "Opcional.")

    def test_busqueda_nombre_completo(self):
        documento = self.documento()
        self.assertQuerySetEqual(self.buscar(documento.nombre_original).context["documentos"], [documento])

    def test_busqueda_fragmento_nombre(self):
        documento = self.documento()
        self.assertQuerySetEqual(self.buscar("septiembre").context["documentos"], [documento])

    def test_busqueda_descripcion_completa(self):
        documento = self.documento(descripcion="Reunión mensual del comité de comunicación")
        self.assertQuerySetEqual(self.buscar(documento.descripcion).context["documentos"], [documento])

    def test_busqueda_fragmento_descripcion(self):
        documento = self.documento(descripcion="Reunión mensual del comité de comunicación")
        self.assertQuerySetEqual(self.buscar("comunicación").context["documentos"], [documento])

    def test_busqueda_sin_coincidencias(self):
        self.documento()
        response = self.buscar("inexistente")
        self.assertQuerySetEqual(response.context["documentos"], [])
        self.assertContains(response, "No encontramos resultados")

    def test_busqueda_vacia_o_ausente_conserva_documentos_y_orden(self):
        primero = self.documento()
        segundo = self.documento(nombre="Reciente.pdf", descripcion="Reciente")
        self.documento(propietario=self.otro)
        for query in (None, "", "   "):
            with self.subTest(query=query):
                self.assertQuerySetEqual(self.buscar(query).context["documentos"], [segundo, primero])

    def test_documento_sin_descripcion_sigue_disponible(self):
        documento = self.documento()
        self.assertEqual(documento.descripcion, "")
        response = self.client.get(reverse("documentos:document_detail", args=[documento.pk]))
        self.assertContains(response, "Sin descripción.")
        self.assertQuerySetEqual(self.buscar("septiembre").context["documentos"], [documento])
        self.assertQuerySetEqual(self.buscar("comunicación").context["documentos"], [])

    def test_busqueda_no_expone_ajenos_por_nombre_ni_descripcion(self):
        propio = self.documento(descripcion="comunicación")
        ajeno = self.documento(propietario=self.otro, descripcion="comunicación privada")
        # Ser destinatario de otro envío no lo convierte en documento propio.
        envio = EnvioDocumento.objects.create(documento=ajeno, remitente=self.otro)
        DestinatarioDocumento.objects.create(envio=envio, usuario=self.presidente)
        for query in ("septiembre", "comunicación"):
            with self.subTest(query=query):
                self.assertQuerySetEqual(self.buscar(query).context["documentos"], [propio])
        self.assertQuerySetEqual(self.buscar("privada").context["documentos"], [])
        self.assertEqual(self.client.get(reverse("documentos:document_detail", args=[ajeno.pk])).status_code, 404)

    def test_busqueda_combina_estados_y_conserva_termino(self):
        documentos = {}
        for estado in ("unprepared", "preparation", "sent"):
            documento = self.documento(nombre=f"{estado}.pdf", descripcion="comunicación")
            documentos[estado] = documento
            if estado != "unprepared":
                EnvioDocumento.objects.create(
                    documento=documento, remitente=self.presidente,
                    estado=EnvioDocumento.Estado.PREPARACION if estado == "preparation" else EnvioDocumento.Estado.ENVIADO,
                )
        for estado, documento in documentos.items():
            with self.subTest(estado=estado):
                response = self.buscar(" comunicación ", estado=estado)
                self.assertQuerySetEqual(response.context["documentos"], [documento])
                self.assertContains(response, 'value="comunicación"')
                self.assertContains(response, f'?estado={estado}')
                self.assertContains(response, "q=comunicaci%C3%B3n")
                self.assertContains(response, "Limpiar búsqueda")
                self.assertQuerySetEqual(self.buscar(estado=estado).context["documentos"], [documento])
        self.assertEqual(len(self.buscar("comunicación", estado="desconocido").context["documentos"]), 3)

    def test_comodines_sql_se_buscan_como_texto(self):
        self.documento()
        for query in ("%", "_", "' OR 1=1 --"):
            with self.subTest(query=query):
                self.assertQuerySetEqual(self.buscar(query).context["documentos"], [])

    def test_descripcion_en_flujo_completo_con_seis_campos_y_pdf_resultante(self):
        descripcion = "Acta mensual del comité de comunicación"
        archivo = self.pdf()
        original = archivo.read()
        archivo.seek(0)
        self.assertEqual(self.client.post(reverse("documentos:upload"), {
            "archivo": archivo, "descripcion": descripcion,
        }).status_code, 302)
        documento = Documento.objects.get()
        response = self.client.post(reverse("documentos:committee_recipients", args=[documento.pk]), {
            "recipient_mode": "single", "recipients": [self.presidente.pk],
        })
        self.assertRedirects(response, reverse("documentos:document_editor", args=[documento.pk]))
        destinatario = DestinatarioDocumento.objects.get(envio__documento=documento)
        campos = [{
            "type": tipo, "recipient_id": destinatario.pk, "page": 1,
            "x": 0.1, "y": round(0.1 + index * 0.12, 2), "width": 0.6, "height": 0.08,
        } for index, tipo in enumerate(("signature", "name", "date", "text", "initials", "checkbox"))]
        response = self.client.post(reverse("documentos:signature_fields", args=[documento.pk]),
                                    json.dumps({"fields": campos}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(destinatario.campos_firma.values_list("tipo", flat=True)), set(CampoFirma.Tipo.values))
        review = self.client.get(reverse("documentos:send_review", args=[documento.pk]))
        self.assertTrue(review.context["listo_para_enviar"])
        self.assertEqual(self.client.post(reverse("documentos:send", args=[documento.pk])).status_code, 302)
        firma_url = reverse("firmas:recipient_sign", args=[destinatario.pk])
        self.assertEqual(self.client.get(firma_url).status_code, 200)
        png = BytesIO()
        Image.new("RGBA", (100, 40), "black").save(png, format="PNG")
        texto = destinatario.campos_firma.get(tipo=CampoFirma.Tipo.TEXTO)
        checkbox = destinatario.campos_firma.get(tipo=CampoFirma.Tipo.CHECKBOX)
        response = self.client.post(firma_url, {
            "metodo": "DIBUJADA", "consentimiento": "1",
            "firma": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode(),
            "valores_campos": json.dumps({str(texto.pk): "Acuerdo aprobado", str(checkbox.pk): True}),
        })
        self.assertRedirects(response, reverse("documentos:user_completed"))
        destinatario.refresh_from_db()
        self.assertEqual(destinatario.estado, DestinatarioDocumento.Estado.FIRMADO)
        for campo in destinatario.campos_firma.exclude(tipo=CampoFirma.Tipo.FIRMA):
            self.assertIsNotNone(campo.valor)
            self.assertIsNotNone(campo.fecha_completado)
        resultado = DocumentoResultado.objects.get(envio=destinatario.envio)
        with resultado.archivo.open("rb") as output:
            reader = PdfReader(output)
            self.assertEqual(len(reader.pages), 1)
            self.assertIn("Acuerdo aprobado", reader.pages[0].extract_text())
            self.assertNotIn(descripcion, reader.pages[0].extract_text())
        documento.refresh_from_db()
        self.assertEqual(documento.descripcion, descripcion)
        self.assertEqual(documento.hash_sha256, hashlib.sha256(original).hexdigest())
        with documento.archivo.open("rb") as stored:
            self.assertEqual(stored.read(), original)
        self.assertQuerySetEqual(self.buscar("comunicación").context["documentos"], [documento])
        self.assertContains(self.client.get(reverse("documentos:document_detail", args=[documento.pk])), descripcion)


class DescripcionMigracionTests(TestCase):
    def test_migracion_con_documento_preexistente(self):
        anterior = [("documentos", "0007_campos_interactivos")]
        actual = [("documentos", "0008_documento_descripcion")]
        executor = MigrationExecutor(connection)
        executor.migrate(anterior)
        try:
            apps = executor.loader.project_state(anterior).apps
            comite = Comite.objects.create(nombre="Histórico descripción")
            usuario = get_user_model().objects.create_user(
                email="historico-descripcion@adicla.org.gt", comite=comite,
                cargo_id=Cargo.Codigo.MIEMBRO,
            )
            documento = apps.get_model("documentos", "Documento").objects.create(
                propietario_id=usuario.pk, archivo="documentos/historico.pdf",
                nombre_original="histórico.pdf", tamano=10, hash_sha256="a" * 64,
            )
            MigrationExecutor(connection).migrate(actual)
            migrado = Documento.objects.get(pk=documento.pk)
            self.assertEqual(migrado.descripcion, "")
            self.assertEqual(migrado.nombre_original, "histórico.pdf")
            self.assertEqual(migrado.archivo.name, "documentos/historico.pdf")
            self.assertEqual(migrado.hash_sha256, "a" * 64)
        finally:
            MigrationExecutor(connection).migrate(actual)
