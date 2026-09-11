# ADICLA Sign

## Verificación de correo

En desarrollo, cuando `DJANGO_DEBUG=True`, Django utiliza por defecto el backend
de consola. El enlace de verificación se muestra en la terminal y no requiere
una cuenta SMTP real.

Para SMTP, configura las variables documentadas en `.env.example`:
`DJANGO_EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` y `DEFAULT_FROM_EMAIL`.
`EMAIL_VERIFICATION_TIMEOUT` define la vigencia del enlace en segundos y
`EMAIL_VERIFICATION_RESEND_COOLDOWN` el intervalo mínimo entre reenvíos.

La migración conserva las cuentas anteriores como verificadas. Sólo las cuentas
creadas mediante el registro público comienzan pendientes de verificación; las
cuentas creadas por el formulario administrativo se consideran verificadas.
