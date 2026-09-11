from importlib import import_module
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

from django.apps import apps
from django.core import mail
from django.contrib.auth import authenticate, get_user_model
from django.db import connection, IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auditoria.models import EventoAuditoria

from .constants import OFFICIAL_COMMITTEE_NAMES
from .forms import RegistroUsuarioForm
from .models import Cargo, Comite


class AuthPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité de páginas")
        cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.usuario = get_user_model().objects.create_user(
            email="paginas@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Bryan",
            last_name="Pérez",
            comite=comite,
            cargo=cargo,
        )

    def test_home_redirects_to_dashboard(self):
        response = self.client.get("/")

        self.assertRedirects(
            response,
            reverse("usuarios:dashboard"),
            fetch_redirect_response=False,
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse("usuarios:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inicia sesión")

    def test_register_page_renders(self):
        response = self.client.get(reverse("usuarios:register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear cuenta")

    def test_dashboard_page_renders(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hola, Bryan")
        self.assertContains(response, "Requieren tu atención")
        self.assertNotContains(response, "Nuevo documento")

    def test_profile_page_renders(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("usuarios:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mi perfil")
        self.assertContains(response, self.usuario.email)
        self.assertContains(response, self.usuario.comite.nombre)

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertRedirects(
            response,
            f'{reverse("usuarios:login")}?next={reverse("usuarios:dashboard")}',
        )

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.usuario)

        self.assertEqual(self.client.get(reverse("usuarios:logout")).status_code, 405)
        response = self.client.post(reverse("usuarios:logout"))

        self.assertRedirects(response, reverse("usuarios:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_rejects_post_without_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.usuario)

        response = csrf_client.post(reverse("usuarios:logout"))

        self.assertEqual(response.status_code, 403)


class ProfileIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.comite_a = Comite.objects.create(nombre="Comité Identidad A")
        cls.comite_b = Comite.objects.create(nombre="Comité Identidad B")
        cls.usuario_a = get_user_model().objects.create_user(
            email="elena.identidad@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Elena",
            last_name="Caal",
            comite=cls.comite_a,
            cargo=presidente,
        )
        cls.miembro_a = get_user_model().objects.create_user(
            email="miembro.identidad@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Mario",
            last_name="Ixcoy",
            comite=cls.comite_a,
            cargo=miembro,
        )
        cls.usuario_b = get_user_model().objects.create_user(
            email="sofia.identidad@adicla.org.gt",
            password="ClaveSegura!2026",
            first_name="Sofía",
            last_name="Choc",
            comite=cls.comite_b,
            cargo=presidente,
        )

    def test_president_profile_uses_authenticated_user_and_real_committee_data(self):
        self.client.force_login(self.usuario_a)

        response = self.client.get(reverse("usuarios:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elena Caal")
        self.assertContains(response, self.usuario_a.email)
        self.assertContains(response, self.comite_a.nombre)
        self.assertContains(response, self.usuario_a.cargo.nombre)
        self.assertContains(response, "2 integrantes activos")
        self.assertEqual(response.context["active_committee_member_count"], 2)
        for mock_value in (
            "Andrea",
            "Morales",
            "andrea.morales",
            "1.8 GB",
            "5 GB",
            "36%",
            "08:42",
            "Gerente administrativa",
        ):
            self.assertNotContains(response, mock_value)

    def test_different_presidents_see_only_their_own_identity(self):
        self.client.force_login(self.usuario_b)

        response = self.client.get(reverse("usuarios:profile"))

        self.assertContains(response, "Sofía Choc")
        self.assertContains(response, self.usuario_b.email)
        self.assertContains(response, self.comite_b.nombre)
        self.assertNotContains(response, "Elena Caal")
        self.assertNotContains(response, self.usuario_a.email)
        self.assertNotContains(response, self.comite_a.nombre)

    def test_member_profile_uses_real_identity_and_sidebar_count_context(self):
        self.client.force_login(self.miembro_a)

        response = self.client.get(reverse("usuarios:profile"))

        self.assertContains(response, "Mario Ixcoy")
        self.assertContains(response, self.miembro_a.email)
        self.assertContains(response, self.comite_a.nombre)
        self.assertEqual(response.context["pending_count"], 0)
        self.assertContains(response, f'action="{reverse("usuarios:logout")}"')
        self.assertContains(response, 'method="post"')


class RegistroUsuarioTests(TestCase):
    password = "ClaveSegura!2026"

    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nombre="Comité de Registro")
        cls.cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)

    def datos_validos(self, **changes):
        data = {
            "first_name": "Juan Carlos",
            "last_name": "Mogollón Pérez",
            "email": "usuario@adicla.org.gt",
            "comite": self.comite.pk,
            "cargo": self.cargo.codigo,
            "password1": self.password,
            "password2": self.password,
        }
        data.update(changes)
        return data

    def test_registro_correcto_guarda_datos_y_contrasena_hasheada(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(email="  Usuario@ADICLA.ORG.GT "),
        )

        self.assertRedirects(response, reverse("usuarios:login"))
        usuario = get_user_model().objects.get(email="usuario@adicla.org.gt")
        self.assertEqual(usuario.first_name, "Juan Carlos")
        self.assertEqual(usuario.last_name, "Mogollón Pérez")
        self.assertEqual(usuario.comite, self.comite)
        self.assertEqual(usuario.cargo, self.cargo)
        self.assertNotEqual(usuario.password, self.password)
        self.assertTrue(usuario.check_password(self.password))
        self.assertFalse(usuario.email_verificado)
        self.assertIsNone(usuario.fecha_verificacion_email)

    def test_selectores_muestran_datos_de_los_modelos(self):
        response = self.client.get(reverse("usuarios:register"))

        self.assertContains(response, self.comite.nombre)
        self.assertContains(response, self.cargo.nombre)

    def test_registro_publico_no_expone_cargos_directivos(self):
        response = self.client.get(reverse("usuarios:register"))

        for cargo in Cargo.objects.filter(es_directivo=True):
            self.assertNotContains(response, f'value="{cargo.codigo}"')

    def test_registro_publico_rechaza_cargo_directivo_manipulado(self):
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)

        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(cargo=presidente.codigo),
        )

        self.assertFormError(
            response.context["form"],
            "cargo",
            "Escoja una opción válida. Esa opción no está entre las disponibles.",
        )
        self.assertFalse(get_user_model().objects.filter(email="usuario@adicla.org.gt").exists())


    def test_selector_incluye_comites_iniciales(self):
        response = self.client.get(reverse("usuarios:register"))

        for nombre in OFFICIAL_COMMITTEE_NAMES:
            self.assertContains(response, nombre)

    def test_selector_excluye_comites_inactivos(self):
        inactivo = Comite.objects.create(nombre="Comité inactivo", activo=False)

        response = self.client.get(reverse("usuarios:register"))

        self.assertNotContains(response, inactivo.nombre)

    def test_registro_rechaza_comite_inactivo(self):
        inactivo = Comite.objects.create(nombre="Comité deshabilitado", activo=False)

        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(comite=inactivo.pk),
        )

        self.assertFormError(
            response.context["form"],
            "comite",
            "Escoja una opción válida. Esa opción no está entre las disponibles.",
        )

    def test_rechaza_gmail(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(email="usuario@gmail.com"),
        )

        self.assertFormError(
            response.context["form"],
            "email",
            "Ingrese un correo institucional @adicla.org.gt.",
        )

    def test_rechaza_otro_dominio(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(email="usuario@otro.org.gt"),
        )

        self.assertFormError(
            response.context["form"],
            "email",
            "Ingrese un correo institucional @adicla.org.gt.",
        )

    def test_rechaza_subdominio(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(email="usuario@subdominio.adicla.org.gt"),
        )

        self.assertFormError(
            response.context["form"],
            "email",
            "Ingrese un correo institucional @adicla.org.gt.",
        )

    def test_rechaza_correo_institucional_duplicado(self):
        get_user_model().objects.create_user(
            email="usuario@adicla.org.gt",
            password=self.password,
            comite=self.comite,
            cargo=self.cargo,
        )

        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(email="USUARIO@ADICLA.ORG.GT"),
        )

        self.assertFormError(
            response.context["form"],
            "email",
            "Ya existe un usuario con este correo electrónico.",
        )

    def test_rechaza_contrasenas_distintas(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(password2="OtraClave!2026"),
        )

        self.assertFormError(
            response.context["form"],
            "password2",
            "Las contraseñas no coinciden.",
        )

    def test_aplica_validadores_de_contrasena_de_django(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(password1="123", password2="123"),
        )

        self.assertTrue(response.context["form"].errors["password1"])
        self.assertFalse(get_user_model().objects.exists())

    def test_comite_es_obligatorio(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(comite=""),
        )

        self.assertFormError(
            response.context["form"],
            "comite",
            "Este campo es obligatorio.",
        )

    def test_cargo_es_obligatorio(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(cargo=""),
        )

        self.assertFormError(
            response.context["form"],
            "cargo",
            "Este campo es obligatorio.",
        )

    def test_nombres_son_obligatorios(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(first_name=""),
        )

        self.assertFormError(
            response.context["form"],
            "first_name",
            "Este campo es obligatorio.",
        )

    def test_apellidos_son_obligatorios(self):
        response = self.client.post(
            reverse("usuarios:register"),
            self.datos_validos(last_name=""),
        )

        self.assertFormError(
            response.context["form"],
            "last_name",
            "Este campo es obligatorio.",
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_VERIFICATION_TIMEOUT=3600,
    EMAIL_VERIFICATION_RESEND_COOLDOWN=300,
)
class VerificacionEmailTests(TestCase):
    password = "ClaveSegura!2026"

    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nombre="Comité verificación")
        cls.miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)

    def datos_registro(self, **changes):
        datos = {
            "first_name": "Correo",
            "last_name": "Pendiente",
            "email": "pendiente@adicla.org.gt",
            "comite": self.comite.pk,
            "cargo": self.miembro.codigo,
            "password1": self.password,
            "password2": self.password,
        }
        datos.update(changes)
        return datos

    def registrar(self):
        return self.client.post(
            reverse("usuarios:register"),
            self.datos_registro(),
        )

    def ruta_verificacion(self, mensaje=-1):
        linea = next(
            linea
            for linea in mail.outbox[mensaje].body.splitlines()
            if linea.startswith("Verificar correo: ")
        )
        return urlparse(linea.removeprefix("Verificar correo: ")).path

    def test_registro_pendiente_genera_correo_sin_secretos_en_auditoria(self):
        response = self.registrar()
        usuario = get_user_model().objects.get(email="pendiente@adicla.org.gt")

        self.assertRedirects(response, reverse("usuarios:login"))
        self.assertFalse(usuario.email_verificado)
        self.assertIsNone(usuario.fecha_verificacion_email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [usuario.email])
        self.assertNotIn(self.password, mail.outbox[0].body)
        self.assertIn("expira", mail.outbox[0].body)
        for evento in EventoAuditoria.objects.all():
            self.assertNotIn("token", str(evento.informacion_adicional).lower())

    def test_enlace_valido_verifica_y_no_puede_reutilizarse(self):
        self.registrar()
        usuario = get_user_model().objects.get(email="pendiente@adicla.org.gt")
        self.client.force_login(usuario)

        ruta = self.ruta_verificacion()
        confirmacion = self.client.get(ruta)
        usuario.refresh_from_db()

        self.assertEqual(confirmacion.status_code, 200)
        self.assertFalse(usuario.email_verificado)
        self.assertIn("no-store", confirmacion["Cache-Control"])
        self.assertEqual(confirmacion["Referrer-Policy"], "no-referrer")

        response = self.client.post(ruta)
        usuario.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(usuario.email_verificado)
        self.assertIsNotNone(usuario.fecha_verificacion_email)
        self.assertTrue(response.wsgi_request.user.email_verificado)
        self.assertContains(
            self.client.get(reverse("usuarios:dashboard")),
            "Requieren tu atención",
        )
        self.assertEqual(self.client.post(ruta).status_code, 400)

    def test_token_alterado_y_token_expirado_fallan_sin_verificar(self):
        self.registrar()
        ruta = self.ruta_verificacion()
        usuario = get_user_model().objects.get(email="pendiente@adicla.org.gt")

        ruta_alterada = f"{ruta.rstrip('/')}alterado/"
        self.assertEqual(self.client.get(ruta_alterada).status_code, 400)
        with self.settings(EMAIL_VERIFICATION_TIMEOUT=-1):
            self.assertEqual(self.client.get(ruta).status_code, 400)
        usuario.refresh_from_db()
        self.assertFalse(usuario.email_verificado)

    def test_reenvio_invalida_token_anterior_y_limita_repeticiones(self):
        self.registrar()
        usuario = get_user_model().objects.get(email="pendiente@adicla.org.gt")
        token_anterior = self.ruta_verificacion()
        usuario.fecha_ultimo_envio_verificacion = timezone.now() - timedelta(minutes=6)
        usuario.save(update_fields=("fecha_ultimo_envio_verificacion",))

        respuesta = self.client.post(
            reverse("usuarios:resend_verification"),
            {"email": usuario.email},
        )

        self.assertRedirects(respuesta, reverse("usuarios:login"))
        self.assertEqual(len(mail.outbox), 2)
        token_nuevo = self.ruta_verificacion()
        self.assertNotEqual(token_anterior, token_nuevo)
        self.assertEqual(self.client.get(token_anterior).status_code, 400)

        self.client.post(
            reverse("usuarios:resend_verification"),
            {"email": usuario.email},
        )
        self.client.post(
            reverse("usuarios:resend_verification"),
            {"email": "inexistente@adicla.org.gt"},
        )
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.client.post(token_nuevo).status_code, 200)

    def test_confirmacion_requiere_csrf(self):
        self.registrar()
        ruta = self.ruta_verificacion()
        cliente = Client(enforce_csrf_checks=True)

        self.assertEqual(cliente.post(ruta).status_code, 403)
        usuario = get_user_model().objects.get(email="pendiente@adicla.org.gt")
        self.assertFalse(usuario.email_verificado)

    def test_cambio_de_correo_revoca_verificacion(self):
        usuario = get_user_model().objects.create_user(
            email="original@adicla.org.gt",
            password=self.password,
            comite=self.comite,
            cargo=self.miembro,
        )
        self.assertTrue(usuario.email_verificado)

        usuario.email = "nuevo@adicla.org.gt"
        usuario.save(update_fields=("email",))
        usuario.refresh_from_db()

        self.assertFalse(usuario.email_verificado)
        self.assertIsNone(usuario.fecha_verificacion_email)
        self.assertEqual(usuario.version_verificacion_email, 1)

    def test_usuario_historico_y_registro_administrativo_siguen_verificados(self):
        historico = get_user_model().objects.create_user(
            email="historico@adicla.org.gt",
            password=self.password,
            comite=self.comite,
            cargo=self.miembro,
        )
        formulario = RegistroUsuarioForm(
            data=self.datos_registro(email="administrado@adicla.org.gt")
        )

        self.assertTrue(historico.email_verificado)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        administrado = formulario.save()
        self.assertTrue(administrado.email_verificado)
        self.assertIsNotNone(
            authenticate(email=historico.email, password=self.password)
        )

    def test_login_logout_permanecen_disponibles_mientras_esta_pendiente(self):
        self.registrar()

        response = self.client.post(
            reverse("usuarios:login"),
            {"email": "pendiente@adicla.org.gt", "password": self.password},
        )

        self.assertRedirects(response, reverse("usuarios:dashboard"))
        self.assertContains(
            self.client.get(reverse("usuarios:dashboard")),
            "Verifica tu correo",
        )
        self.assertContains(
            self.client.get(reverse("usuarios:profile")),
            "Verifica tu correo",
        )
        self.assertRedirects(
            self.client.post(reverse("usuarios:logout")),
            reverse("usuarios:login"),
        )


class AutenticacionPorCorreoTests(TestCase):
    password = "ClaveSegura!2026"

    @classmethod
    def setUpTestData(cls):
        comite = Comite.objects.create(nombre="Comité de Autenticación")
        cargo = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        cls.usuario = get_user_model().objects.create_user(
            email="login@adicla.org.gt",
            password=cls.password,
            first_name="Usuario",
            last_name="Autenticado",
            comite=comite,
            cargo=cargo,
        )

    def test_autentica_con_correo_institucional_y_contrasena(self):
        usuario = authenticate(
            email="LOGIN@ADICLA.ORG.GT",
            password=self.password,
        )

        self.assertEqual(usuario, self.usuario)

    def test_rechaza_contrasena_incorrecta(self):
        usuario = authenticate(
            email="login@adicla.org.gt",
            password="ContraseñaIncorrecta!2026",
        )

        self.assertIsNone(usuario)

    def test_login_crea_sesion_y_redirige_al_dashboard(self):
        response = self.client.post(
            reverse("usuarios:login"),
            {"email": "LOGIN@ADICLA.ORG.GT", "password": self.password},
        )

        self.assertRedirects(response, reverse("usuarios:dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.usuario.pk)

class EstructuraOrganizacionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comite_a = Comite.objects.create(nombre="Comite A")
        cls.comite_b = Comite.objects.create(nombre="Comite B")
        cls.cargos = {
            codigo: Cargo.objects.get(codigo=codigo)
            for codigo in Cargo.Codigo.values
        }

    def crear_usuario(self, identificador, comite, codigo_cargo):
        return get_user_model().objects.create_user(
            email=f"{identificador}@adicla.org.gt",
            password="contrasena-de-prueba",
            comite=comite,
            cargo=self.cargos[codigo_cargo],
        )

    def test_un_comite_acepta_multiples_usuarios(self):
        self.crear_usuario("miembro1", self.comite_a, Cargo.Codigo.MIEMBRO)
        self.crear_usuario("miembro2", self.comite_a, Cargo.Codigo.MIEMBRO)

        self.assertEqual(self.comite_a.usuarios.count(), 2)

    def test_un_usuario_pertenece_a_un_solo_comite(self):
        usuario = self.crear_usuario(
            "usuario-unico", self.comite_a, Cargo.Codigo.MIEMBRO
        )

        self.assertEqual(usuario.comite, self.comite_a)
        self.assertFalse(self.comite_b.usuarios.filter(pk=usuario.pk).exists())

    def test_diferentes_comites_pueden_tener_presidente(self):
        self.crear_usuario("presidente-a", self.comite_a, Cargo.Codigo.PRESIDENTE)
        self.crear_usuario("presidente-b", self.comite_b, Cargo.Codigo.PRESIDENTE)

        self.assertEqual(
            get_user_model()
            .objects.filter(cargo=Cargo.Codigo.PRESIDENTE)
            .count(),
            2,
        )

    def assert_cargo_directivo_no_se_repite(self, codigo_cargo):
        self.crear_usuario(f"{codigo_cargo}-1", self.comite_a, codigo_cargo)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.crear_usuario(f"{codigo_cargo}-2", self.comite_a, codigo_cargo)

    def test_un_comite_no_puede_tener_dos_presidentes(self):
        self.assert_cargo_directivo_no_se_repite(Cargo.Codigo.PRESIDENTE)

    def test_un_comite_no_puede_tener_dos_vicepresidentes(self):
        self.assert_cargo_directivo_no_se_repite(Cargo.Codigo.VICEPRESIDENTE)

    def test_un_comite_no_puede_tener_dos_secretarios(self):
        self.assert_cargo_directivo_no_se_repite(Cargo.Codigo.SECRETARIO)

    def test_un_comite_no_puede_tener_dos_tesoreros(self):
        self.assert_cargo_directivo_no_se_repite(Cargo.Codigo.TESORERO)

    def test_un_comite_puede_tener_multiples_miembros(self):
        self.crear_usuario("miembro-a", self.comite_a, Cargo.Codigo.MIEMBRO)
        self.crear_usuario("miembro-b", self.comite_a, Cargo.Codigo.MIEMBRO)
        self.crear_usuario("miembro-c", self.comite_a, Cargo.Codigo.MIEMBRO)

        self.assertEqual(
            self.comite_a.usuarios.filter(cargo=Cargo.Codigo.MIEMBRO).count(),
            3,
        )


class MigracionComitesOficialesTests(TestCase):
    password = "ClaveSegura!2026"

    def ejecutar_migracion(self):
        migration = import_module(
            "usuarios.migrations.0006_configurar_comites_oficiales"
        )
        migration.configurar_comites_oficiales(
            apps,
            SimpleNamespace(connection=connection),
        )

    def test_consolida_historicos_y_es_idempotente(self):
        Comite.objects.all().delete()
        liderazgo = Comite.objects.create(
            nombre=OFFICIAL_COMMITTEE_NAMES[0],
            activo=False,
        )
        comunicacion = Comite.objects.create(nombre=OFFICIAL_COMMITTEE_NAMES[1])
        trabajo_equipo = Comite.objects.create(nombre=OFFICIAL_COMMITTEE_NAMES[2])
        recursos_humanos = Comite.objects.create(nombre="Recursos Humanos")
        tecnologia = Comite.objects.create(nombre="Tecnología")
        finanzas = Comite.objects.create(nombre="Finanzas")
        direccion = Comite.objects.create(nombre="Dirección Ejecutiva")
        secretaria = Comite.objects.create(nombre="Secretaría")
        miembro = Cargo.objects.get(codigo=Cargo.Codigo.MIEMBRO)
        presidente = Cargo.objects.get(codigo=Cargo.Codigo.PRESIDENTE)
        usuarios = {
            email: get_user_model().objects.create_user(
                email=email,
                password=self.password,
                comite=comite,
                cargo=cargo,
            )
            for email, comite, cargo in (
                ("usuario.ejemplo@adicla.org.gt", tecnologia, miembro),
                ("usuario.prueba@adicla.org.gt", tecnologia, miembro),
                ("admin.ejemplo@adicla.org.gt", tecnologia, presidente),
                ("usuario.prueba2@adicla.org.gt", finanzas, miembro),
            )
        }

        self.ejecutar_migracion()
        self.ejecutar_migracion()

        self.assertEqual(
            Comite.objects.filter(nombre__in=OFFICIAL_COMMITTEE_NAMES).count(),
            3,
        )
        self.assertEqual(
            set(Comite.objects.filter(activo=True).values_list("nombre", flat=True)),
            set(OFFICIAL_COMMITTEE_NAMES),
        )
        self.assertEqual(
            Comite.objects.get(nombre="Recursos Humanos").activo,
            False,
        )
        self.assertFalse(direccion.__class__.objects.get(pk=direccion.pk).activo)
        self.assertFalse(secretaria.__class__.objects.get(pk=secretaria.pk).activo)
        self.assertEqual(liderazgo.usuarios.count(), 0)

        for usuario in usuarios.values():
            usuario.refresh_from_db()
        self.assertEqual(usuarios["usuario.ejemplo@adicla.org.gt"].comite, comunicacion)
        self.assertEqual(usuarios["usuario.prueba@adicla.org.gt"].comite, comunicacion)
        self.assertEqual(usuarios["admin.ejemplo@adicla.org.gt"].comite, comunicacion)
        self.assertEqual(
            usuarios["admin.ejemplo@adicla.org.gt"].cargo_id,
            Cargo.Codigo.PRESIDENTE,
        )
        self.assertEqual(
            usuarios["usuario.prueba2@adicla.org.gt"].comite,
            trabajo_equipo,
        )
        self.assertFalse(recursos_humanos.__class__.objects.get(pk=recursos_humanos.pk).activo)
        self.assertFalse(tecnologia.__class__.objects.get(pk=tecnologia.pk).activo)
        self.assertFalse(finanzas.__class__.objects.get(pk=finanzas.pk).activo)

    def test_reutiliza_registro_historico_si_el_oficial_no_existe(self):
        Comite.objects.all().delete()
        tecnologia = Comite.objects.create(nombre="Tecnología")

        self.ejecutar_migracion()

        comunicacion = Comite.objects.get(nombre=OFFICIAL_COMMITTEE_NAMES[1])
        self.assertEqual(comunicacion.pk, tecnologia.pk)
        self.assertTrue(comunicacion.activo)

    def test_crea_oficiales_si_no_existen(self):
        Comite.objects.all().delete()

        self.ejecutar_migracion()

        self.assertEqual(
            set(Comite.objects.filter(activo=True).values_list("nombre", flat=True)),
            set(OFFICIAL_COMMITTEE_NAMES),
        )
