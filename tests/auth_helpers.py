"""Explicit test setup for real DB sessions; no production auth override."""
import uuid
from api.auth import issue_session
from api.database import SessionLocal,User
from api.security import hash_password
def authenticate(client,user_id=None):
    user_id=user_id or 'test-'+uuid.uuid4().hex
    with SessionLocal() as db:
        if db.get(User,user_id) is None:
            db.add(User(user_id=user_id,email=f'{user_id}@example.com',nickname=user_id,password_hash=hash_password('test-password')))
            db.commit()
        token,_=issue_session(db,user_id)
    client.headers['Authorization']='Bearer '+token
    client.test_user_id=user_id
    return user_id
