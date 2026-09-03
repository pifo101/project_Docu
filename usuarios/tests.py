from django.contrib.auth import get_user_model
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
        self.assertContains(response, "Regístrate gratis")

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


class EstructuraOrganizacionalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.comite_a = Comite.objects.create(nombre="Comite A")
        cls.comite_b = Comite.objects.create(nombre="Comite B")
        cls.cargos = {
            codigo: Cargo.objects.get(codigo=codigo)
            for codigo in Cargo.Codigo.values
        }

    def crear_usuario(self, username, comite, codigo_cargo):
        return get_user_model().objects.create_user(
            username=username,
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
