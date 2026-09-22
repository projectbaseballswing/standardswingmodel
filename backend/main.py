"""FastAPI 앱 조립.

실행:
    uvicorn backend.main:app --reload

의존성: fastapi, uvicorn, sqlalchemy, pydantic, bcrypt
"""

from fastapi import FastAPI

from backend import login, me, register

app = FastAPI(title="Swing Analysis Auth API")

app.include_router(register.router)
app.include_router(login.router)
app.include_router(me.router)
