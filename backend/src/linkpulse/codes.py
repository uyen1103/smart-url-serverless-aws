import secrets
import string

from .validation import RESERVED_ALIASES

ALPHABET = string.ascii_letters + string.digits  # Base62


def generate_code(length=7):
    """Random Base62 bằng `secrets` (an toàn mật mã) để mã khó đoán/dò (enumeration)."""
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if code.lower() not in RESERVED_ALIASES:
            return code
