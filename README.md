# ADICLA Sign

## Correo electrónico

Actualmente el MVP no utiliza verificación de correo porque el entorno de
despliegue disponible no proporciona un remitente/servicio SMTP para esta
función. El registro público crea una cuenta funcional que puede iniciar sesión
inmediatamente; el sistema no genera tokens ni envía mensajes de verificación.

La configuración SMTP general se conserva en `config/settings.py` y
`.env.example` para posibles funcionalidades futuras, pero no se utiliza en el
flujo actual del MVP.
