"""RailSpeed settings (development defaults; override with environment variables)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Read KEY=VALUE lines from a local .env file (values already set in the environment win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

# Load KEY=value lines from a .env file next to manage.py (no extra package needed).
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me-railspeed")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
# Hosting behind HTTPS (e.g. PythonAnywhere): trust the proxy's https flag and the site's own origin for forms.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "booking",
]

# REST API (/api/): log in with the browser session or a token from POST /api/auth/token/
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "railspeed.urls"

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
                "booking.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "railspeed.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Slips are stored here but never exposed directly; they are served by a permission-checked view.
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --- RailSpeed settings ---
HOLD_MINUTES = int(os.environ.get("RAILSPEED_HOLD_MINUTES", "15"))
MAX_SEATS_PER_BOOKING = 4
PROMPTPAY_ID = os.environ.get("RAILSPEED_PROMPTPAY_ID", "0812345678")  # test number, change to yours
PROMPTPAY_NAME = os.environ.get("RAILSPEED_PROMPTPAY_NAME", "RailSpeed (บัญชีทดสอบ)")
SLIP_MAX_BYTES = 5 * 1024 * 1024
# Demo mode: the QR asks for (price / divisor), e.g. 100 -> a 441-baht ticket is paid as 4.41 baht. 1 = real price.
PAY_DIVISOR = max(1, int(os.environ.get("RAILSPEED_PAY_DIVISOR", "1") or 1))

# AI chat: OpenRouter (free models) is used when OPENROUTER_API_KEY is set, otherwise Anthropic.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODELS = [m.strip() for m in os.environ.get(
    "OPENROUTER_MODELS", "meta-llama/llama-3.3-70b-instruct:free,meta-llama/llama-4-maverick:free").split(",") if m.strip()]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CHAT_ALLOW_TRAVEL = os.environ.get("RAILSPEED_CHAT_ALLOW_TRAVEL", "1") == "1"
CHAT_LIMIT_PER_HOUR = int(os.environ.get("RAILSPEED_CHAT_LIMIT", "20"))