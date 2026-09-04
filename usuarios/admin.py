from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import RegistroUsuarioForm, UsuarioAdminChangeForm
from .models import Cargo, Comite, Usuario


@admin.register(Comite)
class ComiteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "fecha_creacion", "fecha_actualizacion")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "es_directivo")
    list_filter = ("es_directivo",)
    search_fields = ("nombre", "codigo")


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = RegistroUsuarioForm
    form = UsuarioAdminChangeForm
    model = Usuario
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Información personal", {"fields": ("first_name", "last_name")}),
        ("Organización", {"fields": ("comite", "cargo")}),
        (
            "Permisos",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Fechas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "comite",
                    "cargo",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    list_display = (
        "email",
        "first_name",
        "last_name",
        "comite",
        "cargo",
        "is_staff",
    )
    list_filter = UserAdmin.list_filter + ("comite", "cargo")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
