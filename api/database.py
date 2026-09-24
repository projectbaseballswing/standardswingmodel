"""DB: User 테이블 관리"""

from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

engine = create_engine("sqlite:///./users.db", echo=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    # 스펙의 "id" = 로그인용 사용자 아이디 (문자열)
    user_id: Mapped[str] = mapped_column("id", String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)


Base.metadata.create_all(engine)


def get_db():
    """FastAPI 의존성: 요청마다 DB 세션을 열고 닫는다."""
    with Session(engine) as session:
        yield session
