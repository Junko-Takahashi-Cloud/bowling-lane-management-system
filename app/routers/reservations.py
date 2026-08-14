"""
予約関連エンドポイント

重要な設計判断（レビューで確定）：
- 二重予約チェックは2種類必要
  1) E001: 同一 lane_set_id × date で時間帯が重なる予約がないか
  2) E002: 同一 user_id × date で時間帯が重なる予約が既にないか（レーンセットが違っても対象）
- SQLiteは真の行ロックが弱いため、check→insertの間のレースコンディションを防ぐには
  本来 "BEGIN IMMEDIATE" 相当のロックが必要。
  ここではポートフォリオのMVP規模（単一プロセス想定）として、
  プロセス内 threading.Lock で予約作成をシリアライズする簡易対応にしている。
  → 複数プロセス/ワーカーで動かす本番運用や、PostgreSQL移行時は、
     DB側の SELECT ... FOR UPDATE や UNIQUE制約 + リトライに置き換えること。
- キャンセルは論理削除（status='cancelled'）。物理削除はしない。
- キャンセル権限: 本人 or 管理者のみ（get_current_user依存関数で判定）

【3-2追記】
- 予約変更API(update_reservation)を追加。reservation_type='class'の予約は、
  ClassSessionとの整合性が崩れるため対象外(教室と紐づかないgeneral/practice/group等のみ変更可)。
- _has_overlap に exclude_reservation_id を追加(変更対象自身を重複判定から除外するため)。
  デフォルトNoneのため、既存の呼び出し元(本ファイルの作成処理、class_courses.py)への影響なし。
"""
import threading
from datetime import datetime, timezone, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import get_db
from app.models.models import Reservation, LaneSet, User, GroupReservationDetail, ClassEnrollment, ClassCourse
from app.schemas.schemas import (
    ReservationCreate, ReservationOut, ReservationUpdate,
    GroupReservationCreate, GroupReservationOut,
)
from app.utils.auth import get_current_user

router = APIRouter(prefix="/reservations", tags=["reservations"])

JST = ZoneInfo("Asia/Tokyo")


def _is_certified(db: Session, user_id: int) -> bool:
    """一般利用の資格判定：キャンセルしていない個人教室申込を持ち、
    そのコースの最終回（5回目）の日付が既に過ぎていれば「修了済み」とみなす。
    出席そのものまではチェックしない（MVPの割り切り）。
    職場等の団体申込（ClassGroupEnrollment）は個人アカウントに紐づかないため対象外。
    """
    enrollments = (
        db.query(ClassEnrollment)
        .join(ClassCourse, ClassEnrollment.course_id == ClassCourse.course_id)
        .filter(ClassEnrollment.user_id == user_id, ClassEnrollment.status == "enrolled")
        .all()
    )
    today = date.today()
    for e in enrollments:
        course = e.course
        last_session_date = course.first_date + timedelta(weeks=course.session_count - 1)
        if last_session_date <= today:
            return True
    return False

# MVP簡易対応: プロセス内ロックで予約作成をシリアライズ（上記docstring参照）
_reservation_lock = threading.Lock()


def _has_overlap(
    db: Session,
    *,
    filters,
    new_start,
    new_end,
    exclude_status="cancelled",
    exclude_reservation_id: Optional[int] = None,
):
    """時間帯オーバーラップの共通チェック。
    「新規の開始 < 既存の終了」かつ「新規の終了 > 既存の開始」で重複と判定。

    exclude_reservation_id: 指定した場合、その予約自身は重複判定の対象から除外する。
    予約変更(update_reservation)で、変更対象の予約と自分自身を比較して
    誤って「重複」と判定されるのを防ぐために使用する。デフォルトNoneなら
    従来通りの挙動(既存呼び出し元に影響なし)。
    """
    query = db.query(Reservation).filter(
        Reservation.status != exclude_status,
        Reservation.start_time < new_end,
        Reservation.end_time > new_start,
        *filters,
    )
    if exclude_reservation_id is not None:
        query = query.filter(Reservation.reservation_id != exclude_reservation_id)
    return db.query(query.exists()).scalar()


@router.get("/availability")
def get_availability(target_date: str, db: Session = Depends(get_db)):
    """指定日の各レーンセットの予約状況を返す（簡易版：予約一覧をそのまま返す）"""
    lane_sets = db.query(LaneSet).all()
    reservations = (
        db.query(Reservation)
        .filter(Reservation.date == target_date, Reservation.status == "reserved")
        .all()
    )
    return {
        "date": target_date,
        "lane_sets": [
            {"lane_set_id": ls.lane_set_id, "name": ls.name, "status": ls.status}
            for ls in lane_sets
        ],
        "reservations": [
            {
                "lane_set_id": r.lane_set_id,
                "start_time": r.start_time.isoformat(),
                "end_time": r.end_time.isoformat(),
            }
            for r in reservations
        ],
    }


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lane_set = db.query(LaneSet).filter(LaneSet.lane_set_id == payload.lane_set_id).first()
    if lane_set is None:
        raise HTTPException(status_code=404, detail="指定されたレーンセットが存在しません")
    if lane_set.status != "available":
        raise HTTPException(status_code=409, detail="このレーンセットは現在メンテナンス中です")

    if payload.reservation_type == "general" and not _is_certified(db, current_user.user_id):
        raise HTTPException(
            status_code=403,
            detail="一般利用は初心者教室を修了した方のみご利用いただけます。まずは初心者教室にお申し込みください。",
        )

    with _reservation_lock:
        # E001: レーンセット単位の重複チェック
        laneset_conflict = _has_overlap(
            db,
            filters=[Reservation.lane_set_id == payload.lane_set_id,
                     Reservation.date == payload.date],
            new_start=payload.start_time,
            new_end=payload.end_time,
        )
        if laneset_conflict:
            raise HTTPException(
                status_code=409,
                detail="E001: この時間帯・レーンセットは既に予約されています",
            )

        # E002: 同一利用者の時間帯重複チェック（レーンセット違いでも対象）
        user_conflict = _has_overlap(
            db,
            filters=[Reservation.user_id == current_user.user_id,
                     Reservation.date == payload.date],
            new_start=payload.start_time,
            new_end=payload.end_time,
        )
        if user_conflict:
            raise HTTPException(
                status_code=409,
                detail="E002: 同じ時間帯に別の予約が既に存在します",
            )

        reservation = Reservation(
            user_id=current_user.user_id,
            lane_set_id=payload.lane_set_id,
            date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            reservation_type=payload.reservation_type,
            status="reserved",
        )
        db.add(reservation)
        db.commit()
        db.refresh(reservation)
        return reservation


@router.post("/group", response_model=GroupReservationOut, status_code=status.HTTP_201_CREATED)
def create_group_reservation(
    payload: GroupReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """クラウドファンディング特典（レーン貸し切り等）用の予約作成。
    教室・団体練習とは無関係。人数の上限チェックは行わない（把握用のheadcountのみ）。"""
    lane_set = db.query(LaneSet).filter(LaneSet.lane_set_id == payload.lane_set_id).first()
    if lane_set is None:
        raise HTTPException(status_code=404, detail="指定されたレーンセットが存在しません")
    if lane_set.status != "available":
        raise HTTPException(status_code=409, detail="このレーンセットは現在メンテナンス中です")

    with _reservation_lock:
        # E001: レーンセット単位の重複チェック（個人予約・教室予約と同じロジックを共有）
        laneset_conflict = _has_overlap(
            db,
            filters=[Reservation.lane_set_id == payload.lane_set_id,
                     Reservation.date == payload.date],
            new_start=payload.start_time,
            new_end=payload.end_time,
        )
        if laneset_conflict:
            raise HTTPException(
                status_code=409,
                detail="E001: この時間帯・レーンセットは既に予約されています",
            )

        reservation = Reservation(
            user_id=current_user.user_id,
            lane_set_id=payload.lane_set_id,
            date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            reservation_type="group",
            status="reserved",
        )
        db.add(reservation)
        db.flush()  # reservation_id を確定させる

        detail = GroupReservationDetail(
            reservation_id=reservation.reservation_id,
            contact_name=payload.contact_name,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            headcount=payload.headcount,
        )
        db.add(detail)
        db.commit()
        db.refresh(reservation)
        db.refresh(detail)

        return GroupReservationOut(
            reservation_id=reservation.reservation_id,
            lane_set_id=reservation.lane_set_id,
            date=reservation.date,
            start_time=reservation.start_time,
            end_time=reservation.end_time,
            contact_name=detail.contact_name,
            contact_email=detail.contact_email,
            contact_phone=detail.contact_phone,
            headcount=detail.headcount,
            status=reservation.status,
        )


@router.get("/me", response_model=list[ReservationOut])
def list_my_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Reservation)
        .filter(Reservation.user_id == current_user.user_id)
        .order_by(Reservation.date, Reservation.start_time)
        .all()
    )


@router.get("/{reservation_id}", response_model=ReservationOut)
def get_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")
    if current_user.role != "admin" and reservation.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="E003: この予約を閲覧する権限がありません")
    return reservation


def _apply_reservation_update(
    db: Session,
    reservation: Reservation,
    payload: ReservationUpdate,
) -> Reservation:
    """予約変更の実処理(認証・所有者チェックは含まない)。
    User用(update_reservation)・Staff用(staff.py側)の両方から共通で呼び出す。
    class予約の変更禁止・過去日時チェック(JST)・重複チェックは、
    呼び出し元(User/Staff)を問わず同一のルールを適用する。
    """
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="キャンセル済みの予約は変更できません")

    if reservation.reservation_type == "class":
        raise HTTPException(
            status_code=409,
            detail="教室予約(class)はこのAPIでは変更できません。"
                   "ClassSessionとの整合性が崩れるため、教室の日程変更は別途対応が必要です。",
        )

    # 未指定項目は既存値を維持した「変更後の値」を組み立てる
    new_lane_set_id = payload.lane_set_id or reservation.lane_set_id
    new_date = payload.date or reservation.date
    new_start = payload.start_time or reservation.start_time
    new_end = payload.end_time or reservation.end_time

    if new_end <= new_start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    # 過去日時チェック(date+start_timeを結合してJSTで比較)
    new_start_dt = datetime.combine(new_date, new_start, tzinfo=JST)
    if new_start_dt < datetime.now(JST):
        raise HTTPException(status_code=422, detail="過去の日時には変更できません")

    lane_set = db.query(LaneSet).filter(LaneSet.lane_set_id == new_lane_set_id).first()
    if lane_set is None:
        raise HTTPException(status_code=404, detail="指定されたレーンセットが存在しません")
    if lane_set.status != "available":
        raise HTTPException(status_code=409, detail="このレーンセットは現在メンテナンス中です")

    reservation_id = reservation.reservation_id

    with _reservation_lock:
        # E001: レーンセット単位の重複チェック（自分自身は除外）
        laneset_conflict = _has_overlap(
            db,
            filters=[Reservation.lane_set_id == new_lane_set_id,
                     Reservation.date == new_date],
            new_start=new_start,
            new_end=new_end,
            exclude_reservation_id=reservation_id,
        )
        if laneset_conflict:
            raise HTTPException(
                status_code=409,
                detail="E001: この時間帯・レーンセットは既に予約されています",
            )

        # E002: 同一利用者の時間帯重複チェック（自分自身は除外）
        user_conflict = _has_overlap(
            db,
            filters=[Reservation.user_id == reservation.user_id,
                     Reservation.date == new_date],
            new_start=new_start,
            new_end=new_end,
            exclude_reservation_id=reservation_id,
        )
        if user_conflict:
            raise HTTPException(
                status_code=409,
                detail="E002: 同じ時間帯に別の予約が既に存在します",
            )

        reservation.lane_set_id = new_lane_set_id
        reservation.date = new_date
        reservation.start_time = new_start
        reservation.end_time = new_end
        db.commit()
        db.refresh(reservation)
        return reservation


@router.patch("/{reservation_id}", response_model=ReservationOut)
def update_reservation(
    reservation_id: int,
    payload: ReservationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """予約変更(3-2、お客様本人 or admin User用)。部分更新(未指定の項目は既存値を維持)。
    実際の更新ロジック・検証は _apply_reservation_update に共通化されている
    (スタッフ用エンドポイント app/routers/staff.py と共有)。
    """
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    # E003: 本人 or 管理者のみ変更可能（キャンセルと同じ権限方針）
    if current_user.role != "admin" and reservation.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="E003: この予約を変更する権限がありません")

    return _apply_reservation_update(db, reservation, payload)


@router.delete("/{reservation_id}", response_model=ReservationOut)
def cancel_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reservation = db.query(Reservation).filter(
        Reservation.reservation_id == reservation_id
    ).first()
    if reservation is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    # E003: 本人 or 管理者のみキャンセル可能
    if current_user.role != "admin" and reservation.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="E003: この予約をキャンセルする権限がありません")

    # E004相当: キャンセル済みへの再操作は不可
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="この予約は既にキャンセル済みです")

    reservation.status = "cancelled"
    reservation.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return reservation