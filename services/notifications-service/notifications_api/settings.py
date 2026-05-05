import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def _load_env_file(path):
    env_map = {}
    if not path.exists():
        return env_map
    for line in path.read_text(encoding='utf-8').splitlines():
        raw = line.strip()
        if not raw or raw.startswith('#') or '=' not in raw:
            continue
        key, value = raw.split('=', 1)
        env_map[key.strip()] = value.strip().strip('"').strip("'")
    return env_map

_secure_env_override = os.environ.get('NOTIFICATIONS_API_SECURE_ENV_FILE')
if _secure_env_override:
    SECURE_ENV_FILES = [Path(_secure_env_override)]
else:
    SECURE_ENV_FILES = [BASE_DIR / 'env.secure', BASE_DIR / '.env.secure']

SECURE_ENV = {}
for _secure_path in SECURE_ENV_FILES:
    SECURE_ENV.update(_load_env_file(_secure_path))

SECURE_ENV_FILE = SECURE_ENV_FILES[-1]


def _secret(name, default=''):
    return os.environ.get(name) or SECURE_ENV.get(name) or default


SECRET_KEY = 'django-insecure-%jg26zl(@1=&5fs(ax(ec_43d_$%i8p9b++n4vqmm(v%&27udp'

DEBUG = True

ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    'notifications-api,localhost,127.0.0.1'
).split(',')



INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'notifications_api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'notifications_api.wsgi.application'



DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'brfn_db'),
        'USER': os.environ.get('DB_USER', 'brfn_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'brfn_password'),
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': os.environ.get('DB_PORT', '3306'),
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
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SERVICE_SECRET_KEY = os.environ.get('NOTIFICATIONS_API_SECRET_KEY', 'change-this-secret')
SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000')