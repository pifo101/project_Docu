import shutil
import tempfile

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings

from documentos.models import Documento, EnvioDocumento
from usuarios.models import Cargo, Comite

from .admin import EventoAuditoriaAdmin
from .models import EventoAuditoria
from .services import registrar_evento


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EventoAuditoriaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité de auditoría")
        cls.usuario = get_user_model().objects.create_user(
            email="auditoria@adicla.org.gt",
            password="ClaveSegura!2026",
            comite=comite,
            cargo=Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO),
        )
        cls.documento = Documento.objects.create(
            propietario=cls.usuario,
            archivo=SimpleUploadedFile("auditoria.pdf", b"%PDF-1.7\nauditoria"),
            nombre_original="auditoria.pdf",
        )
        cls.envio = EnvioDocumento.objects.create(
            documento=cls.documento,
            remitente=cls.usuario,
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def test_registra_evento_con_documento_proceso_actor_e_ip(self):
        request = RequestFactory().get(
            "/documentos/",
            REMOTE_ADDR="2001:db8::1",
            HTTP_X_FORWARDED_FOR="192.0.2.1",
        )
        request.user = self.usuario

        evento = registrar_evento(
            tipo=EventoAuditoria.Tipo.DOCUMENTO_ENVIADO,
            envio=self.envio,
            request=request,
            informacion_adicional={"cantidad_destinatarios": 2},
        )

        self.assertEqual(evento.documento, self.documento)
        self.assertEqual(evento.envio, self.envio)
        self.assertEqual(evento.actor, self.usuario)
        self.assertEqual(evento.direccion_ip, "2001:db8::1")
        self.assertEqual(evento.informacion_adicional, {"cantidad_destinatarios": 2})

    def test_eventos_del_proceso_se_ordenan_cronologicamente(self):
        primero = registrar_evento(
            tipo=EventoAuditoria.Tipo.DOCUMENTO_CREADO,
            documento=self.documento,
            actor=self.usuario,
        )
        segundo = registrar_evento(
            tipo=EventoAuditoria.Tipo.DOCUMENTO_ENVIADO,
            envio=self.envio,
            actor=self.usuario,
        )

        self.assertQuerySetEqual(
            EventoAuditoria.objects.filter(documento=self.documento),
            [primero, segundo],
        )

    def test_rollback_no_conserva_evento(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                registrar_evento(
                    tipo=EventoAuditoria.Tipo.DOCUMENTO_ENVIADO,
                    envio=self.envio,
                    actor=self.usuario,
                )
                raise RuntimeError("fallo de la operación principal")

        self.assertFalse(EventoAuditoria.objects.exists())

    def test_rechaza_tipo_arbitrario(self):
        with self.assertRaises(ValueError):
            registrar_evento(tipo="TOKEN_COPIADO", documento=self.documento)

    def test_admin_no_permite_modificar_eventos(self):
        administracion = EventoAuditoriaAdmin(EventoAuditoria, AdminSite())
        request = RequestFactory().get("/admin/auditoria/eventoauditoria/")

        self.assertFalse(administracion.has_add_permission(request))
        self.assertFalse(administracion.has_change_permission(request))
        self.assertFalse(administracion.has_delete_permission(request))
