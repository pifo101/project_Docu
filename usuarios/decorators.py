from functools import wraps

from django.core.exceptions import PermissionDenied


def email_verificado_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.email_verificado:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped
