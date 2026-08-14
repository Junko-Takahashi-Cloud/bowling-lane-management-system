"""
Staff APIルーター(第三弾・グループC担当)

既存ルーターの命名・レスポンス方針(REST・/api/v1/・複数形snake_case)に合わせる。
既存ルーターファイルは変更せず、新規ファイルとして追加する想定。

【3-2追記】
PATCH /reservations/{reservation_id} (来店者の予約変更、スタッフ用)を追加。
- Staff認証(PINログイン・HTTPBearer)のみを要求。予約の所有者(user_id)は問わない
  (スタッフは来店対応として「誰の予約でも」変更できる想定のため)。
- class予約変更禁止・過去日時チェック(JST)・重複チェックは、既存のUser用
  PATCH /reservations/{id} と同一ルールを適用する。ロジックの二重管理を避けるため、
  reservations.py の _apply_reservation_update をそのまま呼び出す(コピーしない)。
- Staffが無効化(is_active=False)されている場合は、get_current_staff側で
  既に401を返す設計になっている(本ファイルでの追加対応は不要)。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Staff, Reservation
from app.schemas.schemas import (
    StaffCreate, StaffOut, StaffLogin, StaffActiveUpdate, StaffToken,
    ReservationUpdate, ReservationOut,
)
from app.utils.staff_auth import (
    hash_pin,
    authenticate_staff_by_pin,
    create_staff_access_token,
    get_current_staff,
)
from app.routers.reservations import _apply_reservation_update

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(payload: StaffCreate, db: Session = Depends(get_db)):
    """スタッフ新規登録。PIN重複チェックはしない(bcryptハッシュのため事前重複判定不可。
    運用上、同じPINを複数スタッフが持つこと自体は許容する設計)。"""
    staff = Staff(
        name=payload.name,
        pin_hash=hash_pin(payload.pin_code),
        is_active=True,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


@router.post("/login", response_model=StaffToken)
def staff_login(payload: StaffLogin, db: Session = Depends(get_db)):
    staff = authenticate_staff_by_pin(db, payload.pin_code)
    if staff is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PINが一致するスタッフが見つかりません",
        )
    token = create_staff_access_token(staff.staff_id)
    return StaffToken(access_token=token)


@router.get("", response_model=list[StaffOut])
def list_staff(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    return db.query(Staff).all()


@router.patch("/{staff_id}/active", response_model=StaffOut)
def update_staff_active(
    staff_id: int,
    payload: StaffActiveUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """退職者等の無効化。階層管理がないため、ログイン済みスタッフなら誰でも操作可能
    (少人数運営のため。要:変更提案6参照)"""
    staff = db.query(Staff).filter(Staff.staff_id == staff_id).first()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="スタッフが見つかりません")
    staff.is_active = payload.is_active
    db.commit()
    db.refresh(staff)
    return staff


@router.patch("/reservations/{reservation_id}", response_model=ReservationOut)
def staff_update_reservation(
    reservation_id: int,
    payload: ReservationUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """来店者の予約変更(スタッフ用、3-2)。
    予約の所有者(user_id)は問わず、有効なスタッフであれば誰の予約でも変更できる。
    検証ロジック(class予約禁止・過去日時チェック・重複チェック)は
    User用 PATCH /reservations/{id} と共通(_apply_reservation_update)。
    """
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    return _apply_reservation_update(db, reservation, payload)