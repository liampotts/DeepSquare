"""
Django settings for config project.
"""

import os
from pathlib import Path

import dj_database_url


def _parse_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _parse_csv(value, default):
    if not value:
        return default
    return [item.strip() for item in value.split(',') if item.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-i3fuzw5)ra*qpb5m_&)6!!_*yxd^#&yp3uu#^&+e@nm_1x=bc0',
)

DEBUG = _parse_bool(os.getenv('DEBUG'), True)
ALLOWED_HOSTS = _parse_csv(os.getenv('ALLOWED_HOSTS'), ['localhost', '127.0.0.1'])

CSRF_TRUSTED_ORIGINS = _parse_csv(
    os.getenv('CSRF_TRUSTED_ORIGINS'),
    ['http://localhost', 'http://127.0.0.1'],
)
CORS_ALLOW_ALL_ORIGINS = _parse_bool(os.getenv('CORS_ALLOW_ALL_ORIGINS'), DEBUG)
CORS_ALLOWED_ORIGINS = _parse_csv(
    os.getenv('CORS_ALLOWED_ORIGINS'),
    ['http://localhost:5173', 'http://127.0.0.1:5173'],
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _parse_bool(os.getenv('SECURE_SSL_REDIRECT'), True)
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LLM_FEATURE_ENABLED = _parse_bool(os.getenv('LLM_FEATURE_ENABLED'), True)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
LOCAL_LLM_ENABLED = _parse_bool(os.getenv('LOCAL_LLM_ENABLED'), True)
LOCAL_LLM_BASE_URL = os.getenv('LOCAL_LLM_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')

LLM_ALLOWED_MODELS_OPENAI = _parse_csv(
    os.getenv('LLM_ALLOWED_MODELS_OPENAI'),
    ['gpt-4.1-mini', 'gpt-4o-mini'],
)
LLM_ALLOWED_MODELS_ANTHROPIC = _parse_csv(
    os.getenv('LLM_ALLOWED_MODELS_ANTHROPIC'),
    ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest'],
)
LLM_ALLOWED_MODELS_GEMINI = _parse_csv(
    os.getenv('LLM_ALLOWED_MODELS_GEMINI'),
    ['gemini-1.5-pro', 'gemini-1.5-flash'],
)
LLM_ALLOWED_MODELS_LOCAL = _parse_csv(
    os.getenv('LLM_ALLOWED_MODELS_LOCAL'),
    ['llama3.1:8b'],
)

LLM_ADVANCED_CUSTOM_MODEL_ENABLED = _parse_bool(
    os.getenv('LLM_ADVANCED_CUSTOM_MODEL_ENABLED'),
    True,
)
LLM_MOVE_TIMEOUT_SECONDS = float(os.getenv('LLM_MOVE_TIMEOUT_SECONDS', '15'))

ANALYSIS_FEATURE_ENABLED = _parse_bool(os.getenv('ANALYSIS_FEATURE_ENABLED'), True)
ANALYSIS_PROFILE_DEFAULT = os.getenv('ANALYSIS_PROFILE_DEFAULT', 'balanced')
ANALYSIS_MIN_PLIES = int(os.getenv('ANALYSIS_MIN_PLIES', '8'))
ANALYSIS_MAX_PLIES = int(os.getenv('ANALYSIS_MAX_PLIES', '160'))
ANALYSIS_TIME_LIMIT_SECONDS_BALANCED = float(
    os.getenv('ANALYSIS_TIME_LIMIT_SECONDS_BALANCED', '0.10')
)
ANALYSIS_KEY_MOVES_LIMIT = int(os.getenv('ANALYSIS_KEY_MOVES_LIMIT', '5'))
ANALYSIS_TURNING_POINTS_LIMIT = int(os.getenv('ANALYSIS_TURNING_POINTS_LIMIT', '3'))
