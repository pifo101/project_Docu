from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import EventoAuditoria
from documentos.models import Documento

from .constants import OFFICIAL_COMMITTEE_NAMES
from .models import Cargo, Comite


class AdministracionUsuariosTests(TestCase):
    password = "ClaveSegura!2026"

    @classmethod
    def setUpTestData(cls):
        cls.comite_a = Comite.objects.get(nombre=OFFICIAL_COMMITTEE_NAMES[0])
        cls.comite_b = Comite.objects.get(nombre=OFFICIAL_COMMITTEE_NAMES[1])
        cls.comite_c = Comite.objects.get(nombre=OFFICIAL_COMMITTEE_NAMES[2])
        cls.miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        cls.secretario = Cargo.objects.get(codigo=Cargo.Codigo.SECRETARIO)
        cls.manager = get_user_model().objects.create_user(
            email="gestor@adicla.org.gt",
            password=cls.password,
            first_name="Gestora",
            last_name="Organizacional",
            comite=cls.comite_c,
            cargo=cls.miembro,
            is_staff=True,
        )
        cls.manager.user_permissions.add(
            *Permission.objects.filter(
                codename__in=(
                    "view_usuario",
                    "change_usuario",
                    "view_cargo",
                    "view_comite",
                    "view_eventoauditoria",
                )
            )
        )
        cls.target = get_user_model().objects.create_user(
            email="persona@adicla.org.gt",
            password=cls.password,
            first_name="Persona",
            last_name="Gestionada",
            comite=cls.comite_a,
            cargo=cls.miembro,
        )

    def setUp(self):
        self.admin_client = Client()
        self.admin_client.force_login(self.manager)

    def change_url(self, usuario=None):
        return reverse(
            "admin:usuarios_usuario_change",
            args=[(usuario or self.target).pk],
        )

    def cambiar(self, *, usuario=None, comite=None, cargo=None, **extra):
        usuario = usuario or self.target
        data = {
            "comite": (comite or usuario.comite).pk,
            "cargo": (cargo or usuario.cargo).codigo,
            "_save": "Guardar",
        }
        data.update(extra)
        return self.admin_client.post(self.change_url(usuario), data)

    def test_admin_esta_montado_y_requiere_usuario_staff(self):
        self.assertEqual(self.admin_client.get(reverse("admin:index")).status_code, 200)

        anonimo = Client().get(reverse("admin:index"))
        self.assertEqual(anonimo.status_code, 302)
        self.assertIn(reverse("admin:login"), anonimo.url)

        cliente_normal = Client()
        cliente_normal.force_login(self.target)
        normal_response = cliente_normal.post(
            self.change_url(self.target),
            {
                "comite": self.comite_a.pk,
                "cargo": self.presidente.codigo,
                "_save": "Guardar",
            },
        )
        self.assertEqual(normal_response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo, self.miembro)

        presidente = get_user_model().objects.create_user(
            email="presidente-sin-admin@adicla.org.gt",
            password=self.password,
            comite=self.comite_b,
            cargo=self.presidente,
        )
        cliente_presidente = Client()
        cliente_presidente.force_login(presidente)
        response = cliente_presidente.get(reverse("admin:usuarios_usuario_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_cambio_administrativo_requiere_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)

        response = client.post(
            self.change_url(),
            {
                "comite": self.comite_a.pk,
                "cargo": self.secretario.codigo,
                "_save": "Guardar",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo, self.miembro)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_gestor_puede_buscar_y_filtrar_usuarios(self):
        search = self.admin_client.get(
            reverse("admin:usuarios_usuario_changelist"),
            {"q": "persona@adicla.org.gt"},
        )
        filtered = self.admin_client.get(
            reverse("admin:usuarios_usuario_changelist"),
            {"comite": self.comite_a.pk},
        )
        filtered_by_role = self.admin_client.get(
            reverse("admin:usuarios_usuario_changelist"),
            {"cargo__codigo__exact": self.miembro.codigo},
        )

        self.assertEqual(search.status_code, 200)
        self.assertContains(search, self.target.email)
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, self.target.email)
        self.assertNotContains(filtered, self.manager.email)
        self.assertEqual(filtered_by_role.status_code, 200)
        self.assertContains(filtered_by_role, self.target.email)

    def test_formulario_gestor_solo_edita_cargo_y_comite(self):
        response = self.admin_client.get(self.change_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.email)
        self.assertContains(response, "Estado de la cuenta")
        self.assertContains(response, "Activa")
        self.assertNotContains(response, "Desmarque esta opción")
        for field in (
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
            "password",
        ):
            self.assertNotContains(response, f'name="{field}"')

        changed = self.cambiar(
            cargo=self.secretario,
            is_active="",
            is_staff="on",
            is_superuser="on",
            user_permissions=[Permission.objects.first().pk],
        )
        self.assertEqual(changed.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo, self.secretario)
        self.assertTrue(self.target.is_active)
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)
        self.assertFalse(self.target.user_permissions.exists())

        self.target.is_active = False
        self.target.save(update_fields=("is_active",))
        inactive_response = self.admin_client.get(self.change_url())
        self.assertContains(inactive_response, "Inactiva")
        self.assertNotContains(inactive_response, "Desmarque esta opción")

    def test_formulario_superusuario_conserva_is_active_editable(self):
        superuser = get_user_model().objects.create_superuser(
            email="superusuario@adicla.org.gt",
            password=self.password,
            comite=self.comite_c,
            cargo=self.miembro,
        )
        client = Client()
        client.force_login(superuser)

        response = client.get(self.change_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="is_active"')
        self.assertNotContains(response, "Estado de la cuenta")

    def test_gestor_modifica_comite_y_cargo_y_crea_auditoria(self):
        response = self.cambiar(comite=self.comite_b, cargo=self.secretario)

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.comite, self.comite_b)
        self.assertEqual(self.target.cargo, self.secretario)
        evento = EventoAuditoria.objects.get(
            tipo=EventoAuditoria.Tipo.USUARIO_ORG_MODIFICADA
        )
        self.assertEqual(evento.actor, self.manager)
        self.assertEqual(evento.usuario_afectado, self.target)
        self.assertEqual(
            evento.informacion_adicional,
            {
                "cargo_anterior": {
                    "codigo": self.miembro.codigo,
                    "nombre": self.miembro.nombre,
                },
                "cargo_nuevo": {
                    "codigo": self.secretario.codigo,
                    "nombre": self.secretario.nombre,
                },
                "comite_anterior": {
                    "id": self.comite_a.pk,
                    "nombre": self.comite_a.nombre,
                },
                "comite_nuevo": {
                    "id": self.comite_b.pk,
                    "nombre": self.comite_b.nombre,
                },
            },
        )

    def test_guardar_sin_cambio_no_duplica_auditoria(self):
        response = self.cambiar()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_rechaza_cargo_inexistente_sin_cambio_parcial(self):
        response = self.admin_client.post(
            self.change_url(),
            {
                "comite": self.comite_a.pk,
                "cargo": "ADMINISTRADOR",
                "_save": "Guardar",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escoja una opción válida")
        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo, self.miembro)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_rechaza_comite_no_oficial_sin_cambio_parcial(self):
        no_oficial = Comite.objects.create(nombre="Comité no oficial", activo=True)

        response = self.cambiar(comite=no_oficial)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escoja una opción válida")
        self.target.refresh_from_db()
        self.assertEqual(self.target.comite, self.comite_a)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_conflicto_de_presidente_muestra_error_y_no_reemplaza(self):
        existente = get_user_model().objects.create_user(
            email="presidente-existente@adicla.org.gt",
            password=self.password,
            comite=self.comite_a,
            cargo=self.presidente,
        )

        response = self.cambiar(cargo=self.presidente)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "El comité seleccionado ya tiene un presidente.",
        )
        self.target.refresh_from_db()
        existente.refresh_from_db()
        self.assertEqual(self.target.cargo, self.miembro)
        self.assertEqual(existente.cargo, self.presidente)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_fallo_de_auditoria_revierte_el_cambio(self):
        with patch(
            "usuarios.admin.registrar_evento",
            side_effect=RuntimeError("auditoría no disponible"),
        ):
            with self.assertRaises(RuntimeError):
                self.cambiar(cargo=self.secretario)

        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo, self.miembro)
        self.assertFalse(EventoAuditoria.objects.exists())

    def test_cambio_de_cargo_aplica_permisos_sin_nueva_sesion(self):
        cliente_usuario = Client()
        cliente_usuario.force_login(self.target)
        upload_url = reverse("documentos:upload")
        documento = Documento.objects.bulk_create([
            Documento(
                propietario=self.target,
                archivo="documentos/permisos.pdf",
                nombre_original="permisos.pdf",
                tamano=10,
                hash_sha256="0" * 64,
            )
        ])[0]
        recipients_url = reverse(
            "documentos:committee_recipients",
            args=[documento.pk],
        )
        self.assertEqual(cliente_usuario.get(upload_url).status_code, 403)
        self.assertEqual(cliente_usuario.get(recipients_url).status_code, 403)
        self.assertContains(
            cliente_usuario.get(reverse("usuarios:dashboard")),
            "Requieren tu atención",
        )

        self.assertEqual(self.cambiar(cargo=self.presidente).status_code, 302)
        self.assertEqual(cliente_usuario.get(upload_url).status_code, 200)
        self.assertEqual(cliente_usuario.get(recipients_url).status_code, 200)
        self.assertContains(
            cliente_usuario.get(reverse("usuarios:dashboard")),
            "Documentos recientes",
        )

        self.target.refresh_from_db()
        self.assertEqual(self.cambiar(cargo=self.miembro).status_code, 302)
        self.assertEqual(cliente_usuario.get(upload_url).status_code, 403)
        self.assertEqual(cliente_usuario.get(recipients_url).status_code, 403)

    def test_cambio_no_transfiere_documentos_ni_afecta_otros_usuarios(self):
        documento = Documento.objects.bulk_create([
            Documento(
                propietario=self.target,
                archivo="documentos/historico.pdf",
                nombre_original="historico.pdf",
                tamano=10,
                hash_sha256="0" * 64,
            )
        ])[0]
        otro = get_user_model().objects.create_user(
            email="otro@adicla.org.gt",
            password=self.password,
            comite=self.comite_b,
            cargo=self.miembro,
        )

        self.assertEqual(self.cambiar(cargo=self.presidente).status_code, 302)

        documento.refresh_from_db()
        otro.refresh_from_db()
        self.assertEqual(documento.propietario, self.target)
        self.assertEqual(otro.cargo, self.miembro)
        self.assertEqual(otro.comite, self.comite_b)

    def test_auditoria_es_consultable_pero_inmutable(self):
        self.cambiar(cargo=self.secretario)
        evento = EventoAuditoria.objects.get()
        changelist = self.admin_client.get(
            reverse("admin:auditoria_eventoauditoria_changelist")
        )
        detail_url = reverse(
            "admin:auditoria_eventoauditoria_change",
            args=[evento.pk],
        )

        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, self.target.email)
        self.assertEqual(self.admin_client.get(detail_url).status_code, 200)
        self.assertEqual(self.admin_client.post(detail_url, {"tipo": "TOKEN"}).status_code, 403)


class AdministracionUsuariosSoloLecturaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.get(nombre=OFFICIAL_COMMITTEE_NAMES[0])
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.viewer = get_user_model().objects.create_user(
            email="consulta@adicla.org.gt",
            password="ClaveSegura!2026",
            comite=comite,
            cargo=miembro,
            is_staff=True,
        )
        cls.viewer.user_permissions.add(
            Permission.objects.get(codename="view_usuario")
        )
        cls.target = get_user_model().objects.create_user(
            email="consultado@adicla.org.gt",
            password="ClaveSegura!2026",
            comite=comite,
            cargo=miembro,
        )

    def test_permiso_view_consulta_pero_no_modifica(self):
        client = Client()
        client.force_login(self.viewer)
        list_url = reverse("admin:usuarios_usuario_changelist")
        change_url = reverse(
            "admin:usuarios_usuario_change",
            args=[self.target.pk],
        )

        self.assertEqual(client.get(list_url).status_code, 200)
        self.assertEqual(client.get(change_url).status_code, 200)
        self.assertEqual(
            client.post(
                change_url,
                {
                    "comite": self.target.comite_id,
                    "cargo": Cargo.Codigo.PRESIDENTE,
                    "_save": "Guardar",
                },
            ).status_code,
            403,
        )
        self.target.refresh_from_db()
        self.assertEqual(self.target.cargo_id, Cargo.Codigo.MIEMBRO)
