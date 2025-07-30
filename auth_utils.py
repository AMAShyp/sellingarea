# auth_utils.py
import bcrypt

def hash_pin(raw_pin: str) -> str:
    """Return a bcrypt hash of the PIN (UTF-8 → bytes)."""
    return bcrypt.hashpw(raw_pin.encode(), bcrypt.gensalt()).decode()

def verify_pin(raw_pin: str, hashed: str | None) -> bool:
    """
    Safe check: returns True only when raw_pin matches *and*
    the stored hash is a valid bcrypt string.
    """
    if not hashed:                   # None, empty, NULL in DB → fail
        return False
    try:
        return bcrypt.checkpw(raw_pin.encode(), hashed.encode())
    except ValueError:               # “Invalid salt” or other format issues
        return False
