"""
Staff認証ユーティリティ(第三弾・グループC担当)

既存 app/utils/auth.py は一切変更しない。新規ファイルとして追加する。

【設計方針・重要】
既存Userトークンとの混同を避けるため、Staffトークンは別のJWT claimキーを使う。
- User: payload の "sub" キーに user_id を格納(既存 auth.py 通り)
- Staff: payload の "staff_id" キーに staff_id を格納("sub" は使わない)

こうすることで、既存 get_current_user() が万一Staffトークンを受け取っても
"sub" キーが存在せず認証エラーになり、既存Userの認可ロジックに一切影響しない。
逆にget_current_staff()もUserトークンを受け取った場合は"staff_id"キーが
存在しないため弾かれる。トークンの取り違えを構造的に防ぐ設計。

PIN照合方式:
PINは4桁のみでUser側パスワードよりも衝突可能性が高いため、ログインAPIでは
staff_idの事前指定を求めず、in_active=Trueの全スタッフに対してPINをbcrypt照合し、
一致した1件でログインする(少人数運営を前提としたUX。全国チェーン規模では非推奨)。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Staff
from app.utils.auth import SECRET_KEY, ALGORITHM  # 既存の鍵・アルゴリズムを再利用(変更なし)

STAFF_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12時間(1シフト分を想定)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
staff_oauth2_scheme = HTTPBearer(auto_error=False)


def hash_pin(pin_code: str) -> str:
    return pwd_context.hash(pin_code)


def verify_pin(plain_pin: str, pin_hash: str) -> bool:
    return pwd_context.verify(plain_pin, pin_hash)


def create_staff_access_token(staff_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STAFF_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"staff_id": staff_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_staff_by_pin(db: Session, pin_code: str) -> Optional[Staff]:
    """有効なスタッフ全員に対しPINをbcrypt照合し、一致したスタッフを返す。
    一致なしの場合 None を返す(呼び出し側で401にする)。"""
    active_staff = db.query(Staff).filter(Staff.is_active == True).all()  # noqa: E712
    for staff in active_staff:
        if verify_pin(pin_code, staff.pin_hash):
            return staff
    return None


def get_current_staff(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(staff_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Staff:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="スタッフ認証情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        staff_id = payload.get("staff_id")
        if staff_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    staff = db.query(Staff).filter(Staff.staff_id == int(staff_id)).first()
    if staff is None or not staff.is_active:
        raise credentials_exception
    return staff
