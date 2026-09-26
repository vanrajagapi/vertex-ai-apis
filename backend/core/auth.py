from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.config import settings
from models.schemas import TokenData, User, UserInDB
from core.security import verify_password, get_password_hash
from core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

async def get_user(db: AsyncSession, username: str) -> UserInDB:
    result = await db.execute(text("SELECT username, email, full_name, hashed_password, disabled, role FROM users WHERE username = :u"), {"u": username})
    row = result.fetchone()
    if row:
        return UserInDB(
            username=row.username,
            email=row.email,
            full_name=row.full_name,
            role=row.role,
            hashed_password=row.hashed_password,
            disabled=row.disabled
        )
    return None

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
        
    user = await get_user(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_admin_user(current_user: UserInDB = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT role FROM users WHERE username = :u"), {"u": current_user.username})
    row = result.fetchone()
    if not row or row.role != 'admin':
        raise HTTPException(status_code=403, detail="Not enough privileges")
    return current_user
