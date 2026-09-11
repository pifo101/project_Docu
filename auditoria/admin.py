from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "tipo", "documento", "actor", "direccion_ip")
    list_filter = ("tipo", "fecha_hora")
    search_fields = ("documento__id", "envio__id", "actor__email")
    date_hierarchy = "fecha_hora"
    readonly_fields = (
        "documento",
        "envio",
        "actor",
        "tipo",
        "fecha_hora",
        "direccion_ip",
        "informacion_adicional",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
