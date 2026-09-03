import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is disabled"
        )
    SECRET_KEY = "development-only-change-before-deploying"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "usuarios",
    "documentos",
    "firmas",
    "auditoria",
]

AUTH_USER_MODEL = "usuarios.Usuario"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite")

if DB_ENGINE == "mssql":
    db_auth = os.getenv("DB_AUTH", "sql").lower()

    required_database_settings = ["DB_NAME", "DB_HOST"]

    if db_auth == "sql":
        required_database_settings += ["DB_USER", "DB_PASSWORD"]

    missing_database_settings = [
        setting
        for setting in required_database_settings
        if not os.getenv(setting)
    ]

    if missing_database_settings:
        raise ImproperlyConfigured(
            "Missing SQL Server environment variables: "
            + ", ".join(missing_database_settings)
        )

    database_config = {
        "ENGINE": "mssql",
        "NAME": os.environ["DB_NAME"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.getenv("DB_PORT", ""),
        "OPTIONS": {
            "driver": os.getenv(
                "DB_DRIVER",
                "ODBC Driver 18 for SQL Server",
            ),
            "extra_params": os.getenv(
                "DB_EXTRA_PARAMS",
                "Encrypt=yes;TrustServerCertificate=yes",
            ),
        },
    }

    if db_auth == "sql":
        database_config["USER"] = os.environ["DB_USER"]
        database_config["PASSWORD"] = os.environ["DB_PASSWORD"]
    elif db_auth != "windows":
        raise ImproperlyConfigured(
            f"Unsupported DB_AUTH: {db_auth}"
        )

    DATABASES = {
        "default": database_config
    }

elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

else:
    raise ImproperlyConfigured(
        f"Unsupported DB_ENGINE: {DB_ENGINE}"
    )

LANGUAGE_CODE = "es-gt"
TIME_ZONE = "America/Guatemala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
