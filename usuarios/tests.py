from django.test import TestCase
from django.urls import reverse


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
