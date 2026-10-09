from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from django.db import IntegrityError
from django.shortcuts import redirect

from auditoria.models import EventoAuditoria
from auditoria.services import registrar_evento

from .constants import OFFICIAL_COMMITTEE_NAMES
from .forms import (
    RegistroUsuarioForm,
    UsuarioAdminChangeForm,
    es_conflicto_integridad_organizacional,
)
from .models import Cargo, Comite, Usuario


class ComiteActivoFilter(admin.SimpleListFilter):
    title = "comité"
    parameter_name = "comite"

    def lookups(self, request, model_admin):
        return Comite.objects.filter(
            activo=True,
            nombre__in=OFFICIAL_COMMITTEE_NAMES,
        ).values_list("pk", "nombre")

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(comite_id=self.value())
        return queryset


@admin.register(Comite)
class ComiteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "fecha_creacion", "fecha_actualizacion")
    list_filter = ("activo",)
    search_fields = ("nombre",)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "es_directivo")
    list_filter = ("es_directivo",)
    search_fields = ("nombre", "codigo")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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
    list_filter = UserAdmin.list_filter + (ComiteActivoFilter, "cargo")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    organizational_fieldsets = (
        (
            "Usuario",
            {"fields": ("email", "first_name", "last_name", "estado_cuenta")},
        ),
        ("Organización", {"fields": ("comite", "cargo")}),
    )

    @admin.display(description="Estado de la cuenta")
    def estado_cuenta(self, obj):
        return "Activa" if obj.is_active else "Inactiva"

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_fieldsets(request, obj)
        return self.organizational_fieldsets

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_readonly_fields(request, obj)
        return ("email", "first_name", "last_name", "estado_cuenta")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(
                request,
                object_id,
                form_url,
                extra_context,
            )
        except IntegrityError as error:
            if not es_conflicto_integridad_organizacional(error):
                raise
            self.message_user(
                request,
                "No se pudo guardar el cambio porque entra en conflicto con la estructura del comité.",
                level=messages.ERROR,
            )
            return redirect(request.path)

    def save_model(self, request, obj, form, change):
        anterior = None
        if change:
            anterior = (
                Usuario.objects.select_for_update()
                .select_related("cargo", "comite")
                .get(pk=obj.pk)
            )

        super().save_model(request, obj, form, change)

        if not anterior or (
            anterior.cargo_id == obj.cargo_id
            and anterior.comite_id == obj.comite_id
        ):
            return

        registrar_evento(
            tipo=EventoAuditoria.Tipo.USUARIO_ORG_MODIFICADA,
            usuario_afectado=obj,
            request=request,
            informacion_adicional={
                "cargo_anterior": {
                    "codigo": anterior.cargo_id,
                    "nombre": anterior.cargo.nombre,
                },
                "cargo_nuevo": {
                    "codigo": obj.cargo_id,
                    "nombre": obj.cargo.nombre,
                },
                "comite_anterior": {
                    "id": anterior.comite_id,
                    "nombre": anterior.comite.nombre,
                },
                "comite_nuevo": {
                    "id": obj.comite_id,
                    "nombre": obj.comite.nombre,
                },
            },
        )
