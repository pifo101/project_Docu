from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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
    fieldsets = UserAdmin.fieldsets + (
        ("Organizacion", {"fields": ("comite", "cargo")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Organizacion", {"fields": ("comite", "cargo")}),
    )
    list_display = UserAdmin.list_display + ("comite", "cargo")
    list_filter = UserAdmin.list_filter + ("comite", "cargo")
