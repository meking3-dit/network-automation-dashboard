import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet():
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class EncryptedTextField(models.TextField):
    """Encrypts values at rest using a key derived from Django's SECRET_KEY."""

    prefix = "enc::"

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if not value or not isinstance(value, str) or not value.startswith(self.prefix):
            return value
        try:
            return _fernet().decrypt(value[len(self.prefix) :].encode()).decode()
        except InvalidToken:
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value or value.startswith(self.prefix):
            return value
        return self.prefix + _fernet().encrypt(value.encode()).decode()
