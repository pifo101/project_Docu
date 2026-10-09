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
    usuario_afectado=None,
    actor=None,
    request=None,
    informacion_adicional=None,
):
    if tipo not in EventoAuditoria.Tipo.values:
        raise ValueError("El tipo de evento de auditoría no es válido.")
    es_evento_usuario = tipo == EventoAuditoria.Tipo.USUARIO_ORG_MODIFICADA
    if es_evento_usuario != (usuario_afectado is not None):
        raise ValueError("El tipo de evento no corresponde con su contexto.")
    if documento is None and envio is not None:
        documento = envio.documento
    if (documento is None) == (usuario_afectado is None):
        raise ValueError(
            "El evento debe estar asociado a un documento o a un usuario, no a ambos."
        )
    if usuario_afectado is not None and envio is not None:
        raise ValueError("Un evento de usuario no puede estar asociado a un envío.")
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user

    return EventoAuditoria.objects.create(
        tipo=tipo,
        documento=documento,
        envio=envio,
        usuario_afectado=usuario_afectado,
        actor=actor,
        direccion_ip=_direccion_ip(request),
        informacion_adicional=informacion_adicional or {},
    )
