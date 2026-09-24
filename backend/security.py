"""비밀번호 해싱 (bcrypt) (공통).

비밀번호를 bcrypt로 해싱하고, 로그인 시 비밀번호 검증
"""

import bcrypt


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
