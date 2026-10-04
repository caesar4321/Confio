"""Offline suite: python -m ramps.tests.run_stereum. Never loads project secrets."""


def main():
    import unittest
    import django
    import users
    import ramps
    import security
    from django.apps import AppConfig
    from django.conf import settings
    settings.configure(
        SECRET_KEY='isolated-tests',
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes',
                        AppConfig('users', users), AppConfig('ramps', ramps), AppConfig('security', security)],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        AUTH_USER_MODEL='users.User', DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
        USE_TZ=True, STEREUM_ISOLATED_TESTS=True,
    )
    django.setup()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'ramps.tests.test_stereum_client', 'ramps.tests.test_stereum_service',
        'ramps.tests.test_stereum_storage', 'ramps.tests.test_stereum_schema', 'ramps.tests.test_stereum_qr',
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
