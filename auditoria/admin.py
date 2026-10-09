from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha_hora",
        "tipo",
        "documento",
        "usuario_afectado_email",
        "actor_email",
        "direccion_ip",
    )
    list_filter = ("tipo", "fecha_hora")
    search_fields = (
        "documento__id",
        "envio__id",
        "actor__email",
        "usuario_afectado__email",
        "usuario_afectado__first_name",
        "usuario_afectado__last_name",
    )
    date_hierarchy = "fecha_hora"
    readonly_fields = (
        "documento",
        "envio",
        "actor",
        "usuario_afectado",
        "tipo",
        "fecha_hora",
        "direccion_ip",
        "informacion_adicional",
    )

    @admin.display(description="Usuario afectado", ordering="usuario_afectado__email")
    def usuario_afectado_email(self, obj):
        return obj.usuario_afectado.email if obj.usuario_afectado else "-"

    @admin.display(description="Administrador", ordering="actor__email")
    def actor_email(self, obj):
        return obj.actor.email if obj.actor else "-"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
