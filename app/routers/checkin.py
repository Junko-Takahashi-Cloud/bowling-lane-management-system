"""
checkin.py 修正版

【修正5(要求4)】create_checkin:
  - 既存はbroken/maintenanceのみブロックしていたが、in_useのレーンへの
    新規チェックインも防止する。
  - あわせて、チェックイン作成と同時にlane.statusをin_useへ遷移させる。
    (理由: 従来はcheckin.status=checked_inの時点ではlane.statusが
    available のままだったため、同じレーンに対して別の来店受付が
    通ってしまう二重受付の抜け穴があった。チェックインが発生した時点で
    物理的にレーンは使用中になるという実態に合わせ、即座にin_useへ
    遷移させることでこの抜け穴を塞ぐ)
  - update_checkin_status側のin_use遷移ロジックは残す(べき等な操作のため
    実害はなく、既存フローとの後方互換を優先する)

APIパスは既存のまま(/checkin)ではなく複数形(/checkins)に統一
(憲法5章:リソース名は複数形・snake_case)。main.py側のprefixで対応。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import CheckIn, Lane, CheckInStatusEnum, LaneStatusEnum
from app.schemas.schemas import CheckInCreate, CheckInRead, CheckInStatusUpdate

router = APIRouter()


@router.post("", response_model=CheckInRead, status_code=status.HTTP_201_CREATED)
def create_checkin(payload: CheckInCreate, db: Session = Depends(get_db)):
    """来店受付(チェックイン / 体験利用対応)"""
    lane = db.query(Lane).filter(Lane.id == payload.lane_id).first()
    if not lane:
        raise HTTPException(status_code=404, detail="指定されたレーンが存在しません")

    if lane.status in (LaneStatusEnum.broken, LaneStatusEnum.maintenance):
        raise HTTPException(status_code=400, detail="故障・メンテナンス中のレーンは選択できません")
    if lane.status == LaneStatusEnum.in_use:
        raise HTTPException(status_code=400, detail="このレーンは現在使用中のため、新規チェックインできません")

    new_checkin = CheckIn(
        reservation_id=payload.reservation_id,
        lane_id=payload.lane_id,
        status=CheckInStatusEnum.checked_in,
        checkin_time=datetime.now(),
        is_trial=payload.is_trial,
        shoes_rental=payload.shoes_rental,
        ball_rental=payload.ball_rental,
    )
    db.add(new_checkin)

    # チェックイン成立と同時にレーンを使用中にする(二重受付防止)
    lane.status = LaneStatusEnum.in_use

    db.commit()
    db.refresh(new_checkin)
    return new_checkin


@router.patch("/{checkin_id}/status", response_model=CheckInRead)
def update_checkin_status(
    checkin_id: int,
    payload: CheckInStatusUpdate,
    db: Session = Depends(get_db),
):
    """チェックインステータス更新 (checked_in -> in_use -> checked_out)"""
    checkin_item = db.query(CheckIn).filter(CheckIn.id == checkin_id).first()
    if not checkin_item:
        raise HTTPException(status_code=404, detail="チェックインデータが見つかりません")

    checkin_item.status = payload.status
    lane = db.query(Lane).filter(Lane.id == checkin_item.lane_id).first()

    if payload.status == CheckInStatusEnum.in_use and lane:
        lane.status = LaneStatusEnum.in_use  # 既にin_use済みのケースが多いが、べき等なので実害なし
    elif payload.status == CheckInStatusEnum.checked_out:
        checkin_item.checkout_time = datetime.now()
        if lane and lane.status == LaneStatusEnum.in_use:
            lane.status = LaneStatusEnum.available

    db.commit()
    db.refresh(checkin_item)
    return checkin_item


@router.post("/{checkin_id}/checkout", response_model=CheckInRead)
def checkout(checkin_id: int, db: Session = Depends(get_db)):
    """退店・チェックアウト処理"""
    return update_checkin_status(
        checkin_id=checkin_id,
        payload=CheckInStatusUpdate(status=CheckInStatusEnum.checked_out),
        db=db,
    )