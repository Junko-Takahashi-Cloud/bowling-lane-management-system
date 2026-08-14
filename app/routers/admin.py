"""
管理者ルーター

MVP対象: 全予約確認、予約キャンセル、レーン管理（status切替）
MVP対象外: 予約時間変更（要件定義9章の通り。空き確認・競合チェックが必要なため後続フェーズ）
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Reservation, LaneSet
from app.schemas.schemas import ReservationOut, LaneSetOut, LaneSetStatusUpdate
from app.utils.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/reservations", response_model=list[ReservationOut])
def list_all_reservations(db: Session = Depends(get_db)):
    return db.query(Reservation).order_by(Reservation.date, Reservation.start_time).all()


@router.delete("/reservations/{reservation_id}", response_model=ReservationOut)
def admin_cancel_reservation(reservation_id: int, db: Session = Depends(get_db)):
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="この予約は既にキャンセル済みです")

    reservation.status = "cancelled"
    reservation.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation


@router.get("/lanes", response_model=list[LaneSetOut])
def list_lanes(db: Session = Depends(get_db)):
    return db.query(LaneSet).all()


@router.patch("/lanes/{lane_set_id}", response_model=LaneSetOut)
def update_lane_status(
    lane_set_id: str, payload: LaneSetStatusUpdate, db: Session = Depends(get_db)
):
    lane_set = db.query(LaneSet).filter(LaneSet.lane_set_id == lane_set_id).first()
    if lane_set is None:
        raise HTTPException(status_code=404, detail="レーンセットが見つかりません")
    lane_set.status = payload.status
    db.commit()
    db.refresh(lane_set)
    return lane_set
