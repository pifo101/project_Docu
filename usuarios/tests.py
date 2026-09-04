from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Cargo, Comite


class AuthPagesTests(TestCase):
    def test_home_redirects_to_dashboard(self):
        response = self.client.get("/")

        self.assertRedirects(response, reverse("usuarios:dashboard"))

    def test_login_page_renders(self):
        response = self.client.get(reverse("usuarios:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inicia sesión")

    def test_register_page_renders(self):
        response = self.client.get(reverse("usuarios:register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear cuenta")

    def test_dashboard_page_renders(self):
        response = self.client.get(reverse("usuarios:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Buenos días, Andrea")
        self.assertContains(response, "Documentos recientes")

    def test_profile_page_renders(self):
        response = self.client.get(reverse("usuarios:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mi perfil")
        self.assertContains(response, "Información personal")
        self.assertContains(response, "Preferencias")


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

    def test_selectores_muestran_datos_de_los_modelos(self):
        response = self.client.get(reverse("usuarios:register"))

        self.assertContains(response, self.comite.nombre)
        self.assertContains(response, self.cargo.nombre)

    def test_selector_incluye_comites_iniciales(self):
        response = self.client.get(reverse("usuarios:register"))

        self.assertContains(response, "Recursos Humanos")
        self.assertContains(response, "Tecnología")
        self.assertContains(response, "Dirección Ejecutiva")
        self.assertContains(response, "Secretaría")
        self.assertContains(response, "Finanzas")

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
