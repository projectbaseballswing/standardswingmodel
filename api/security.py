"""비밀번호 해싱 (bcrypt) (공통).

비밀번호를 bcrypt로 해싱하고, 로그인 시 비밀번호 검증
"""

import bcrypt


def hash_password(raw: str) -> str:
    encoded = raw.encode("utf-8")
    if not 1 <= len(encoded) <= 72:
        raise ValueError("Invalid password length")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    if len(raw.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
