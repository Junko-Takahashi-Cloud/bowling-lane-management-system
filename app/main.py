from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal
from app.models.models import LaneSet, Lane, LaneStatusEnum
from app.routers import (
    auth, reservations, admin, class_courses,
    lanes, dashboard, checkin, class_management, payments,
    staff,
)

Base.metadata.create_all(bind=engine)


def seed_lane_sets():
    """初期データ: A(1・2番) / B(3・4番) のレーンセットを投入"""
    db: Session = SessionLocal()
    try:
        if db.query(LaneSet).count() == 0:
            db.add_all([
                LaneSet(lane_set_id="A", name="Aセット（1・2番）", status="available"),
                LaneSet(lane_set_id="B", name="Bセット（3・4番）", status="available"),
            ])
            db.commit()
    finally:
        db.close()


def seed_lanes():
    """初期データ: 個別レーン1〜4番を投入(第三弾 Phase3-1・新規テーブル)。
    アメリカン方式のペア構成に合わせ、lane_set_id・pair_numberを対応させる。
    - 1・2番レーン → lane_set_id="A", pair_number=1
    - 3・4番レーン → lane_set_id="B", pair_number=2
    lane_pair(class_sessions側)は先頭レーン番号方式だが、
    Lane.pair_numberはペアの通し番号(1,2...)である点に注意(意味が異なる)。
    """
    db: Session = SessionLocal()
    try:
        if db.query(Lane).count() == 0:
            db.add_all([
                Lane(lane_set_id="A", lane_number=1, pair_number=1, status=LaneStatusEnum.available),
                Lane(lane_set_id="A", lane_number=2, pair_number=1, status=LaneStatusEnum.available),
                Lane(lane_set_id="B", lane_number=3, pair_number=2, status=LaneStatusEnum.available),
                Lane(lane_set_id="B", lane_number=4, pair_number=2, status=LaneStatusEnum.available),
            ])
            db.commit()
    finally:
        db.close()


seed_lane_sets()
seed_lanes()

app = FastAPI(title="スポーツボウリング場予約システム API", version="0.1.0")

# --- 第二弾(既存) ---
app.include_router(auth.router)
app.include_router(reservations.router)
app.include_router(admin.router)
app.include_router(class_courses.router)

# --- 第三弾 Phase3-1(新規) ---
# 憲法5章: APIパスは複数形・snake_case
app.include_router(lanes.router, prefix="/api/v1/lanes", tags=["lanes"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(checkin.router, prefix="/api/v1/checkins", tags=["checkins"])
# class_management.router は内部で /class_courses/... /class_sessions/... の
# 完全パスを持つため、ここでのprefixは /api/v1 のみ(二重prefix防止)
app.include_router(class_management.router, prefix="/api/v1", tags=["class-management"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["payments"])
app.include_router(staff.router)  # staff.router 側で prefix="/api/v1/staff" を既に設定済み


@app.get("/")
def root():
    return {"status": "ok", "service": "bowling-reservation-api"}