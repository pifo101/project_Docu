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
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "usuarios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite")

if DB_ENGINE == "mssql":
    required_database_settings = ["DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"]
    missing_database_settings = [
        setting for setting in required_database_settings if not os.getenv(setting)
    ]
    if missing_database_settings:
        raise ImproperlyConfigured(
            "Missing SQL Server environment variables: "
            + ", ".join(missing_database_settings)
        )

    DATABASES = {
        "default": {
            "ENGINE": "mssql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ["DB_USER"],
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.environ["DB_HOST"],
            "PORT": os.getenv("DB_PORT", "1433"),
            "OPTIONS": {
                "driver": os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
                "extra_params": os.getenv(
                    "DB_EXTRA_PARAMS", "Encrypt=yes;TrustServerCertificate=no"
                ),
            },
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(f"Unsupported DB_ENGINE: {DB_ENGINE}")

LANGUAGE_CODE = "es-gt"
TIME_ZONE = "America/Guatemala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
