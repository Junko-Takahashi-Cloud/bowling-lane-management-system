from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane
from app.schemas.schemas import LaneRead, LaneStatusUpdateP3 as LaneStatusUpdate

router = APIRouter()

@router.get("", response_model=List[LaneRead])
def get_all_lanes(db: Session = Depends(get_db)):
    """全レーンの状態一覧を取得"""
    return db.query(Lane).order_by(Lane.lane_number).all()

@router.patch("/{lane_id}/status", response_model=LaneRead)
def update_lane_status(
    lane_id: int,
    status_update: LaneStatusUpdate,
    db: Session = Depends(get_db)
):
    """レーンの稼働状態（空き/使用中/故障中/メンテ中）を変更"""
    lane = db.query(Lane).filter(Lane.id == lane_id).first()
    if not lane:
        raise HTTPException(status_code=404, detail="レーンが見つかりません")
    
    lane.status = status_update.status
    if status_update.notes is not None:
        lane.notes = status_update.notes
        
    db.commit()
    db.refresh(lane)
    return lane
