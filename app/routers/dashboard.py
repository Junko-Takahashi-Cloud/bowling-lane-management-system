from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane, Reservation, ClassSession
from app.schemas.schemas import (
    DashboardResponse, LaneRead,
    DashboardReservationRead, DashboardClassSessionRead
)

router = APIRouter()

@router.get("/today", response_model=DashboardResponse)
def get_today_dashboard(target_date: date = None, db: Session = Depends(get_db)):
    """当日ダッシュボードデータ（4レーン状態＋当日予約＋当日教室）の一括取得"""
    if target_date is None:
        target_date = date.today()

    lanes = db.query(Lane).order_by(Lane.lane_number).all()
    
    reservations = db.query(Reservation).filter(Reservation.date == target_date).all()
    today_reservations = [
        DashboardReservationRead(
            reservation_id=r.reservation_id,
            user_id=r.user_id,
            lane_set_id=r.lane_set_id,
            start_time=str(r.start_time),
            end_time=str(r.end_time),
            status=r.status
        )
        for r in reservations
    ]

    class_sessions = db.query(ClassSession).filter(ClassSession.date == target_date).all()
    today_class_sessions = [
        DashboardClassSessionRead(
            class_session_id=cs.class_session_id,
            course_id=cs.course_id,
            session_number=cs.session_number,
            start_time=str(cs.start_time),
            end_time=str(cs.end_time),
            lane_pair=cs.lane_pair,
            status=cs.status
        )
        for cs in class_sessions
    ]

    return DashboardResponse(
        lanes=[LaneRead.model_validate(l) for l in lanes],
        today_reservations=today_reservations,
        today_class_sessions=today_class_sessions
    )
