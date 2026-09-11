from ipaddress import ip_address

from .models import EventoAuditoria


def _direccion_ip(request):
    if request is None:
        return None
    valor = request.META.get("REMOTE_ADDR")
    if not valor:
        return None
    try:
        return str(ip_address(valor))
    except ValueError:
        return None


def registrar_evento(
    *,
    tipo,
    documento=None,
    envio=None,
    actor=None,
    request=None,
    informacion_adicional=None,
):
    if tipo not in EventoAuditoria.Tipo.values:
        raise ValueError("El tipo de evento de auditoría no es válido.")
    if documento is None and envio is not None:
        documento = envio.documento
    if documento is None:
        raise ValueError("El evento debe estar asociado a un documento.")
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user

    return EventoAuditoria.objects.create(
        tipo=tipo,
        documento=documento,
        envio=envio,
        actor=actor,
        direccion_ip=_direccion_ip(request),
        informacion_adicional=informacion_adicional or {},
    )
