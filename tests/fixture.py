import shlex
import subprocess

import os

ALEMBIC_CONFIG = os.path.dirname(os.path.realpath(__file__)) + '/../migrations/alembic.ini'


def init_test_client():
    import os
    import app.config as config
    config.TESTING = True
    config.SQLALCHEMY_DATABASE_URI = (os.environ.get('TEST_DATABASE_URL') or 'postgres://flask_sit:flask_sit@localhost:5432/flask_sit')
    config.WTF_CSRF_ENABLED = False
    import start
    start.application = start.create_app(config)
    start.init_all(start.application)
    return start.application.test_client()


def login_as_admin(test_client):
    return test_client.post('/login', data=dict(email='support@betterlife.io', password='password'), follow_redirects=True)
