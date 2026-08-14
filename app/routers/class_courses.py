"""
教室コース関連エンドポイント（第二弾で追加）

設計方針：
- コース作成はadminのみ（教室の開講判断は運営側が行うため）
- コース作成時、first_date からday_of_week間隔（7日ごと）でsession_count回分の
  ClassSessionを自動生成し、各回ごとにReservationも1件作る
  → 既存の _has_overlap（reservations.py）をそのまま再利用し、
    レーンセット×日時の二重予約チェックに乗せる
- 5回のうちどれか1回でも重複があれば、コース全体を作成しない（部分作成を防ぐ）
- 申込（enroll）はコース単位。1回申し込めば全セッション分参加扱いになる
- 定員チェックは ClassEnrollment の status='enrolled' 件数 と capacity を比較
- Reservation.user_id は、コースを作成した管理者のuser_idを紐づける
  （instructor_nameは文字列運用のため、講師のuser_idではなく作成者を記録する簡易対応）
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    ClassCourse, ClassSession, ClassEnrollment, ClassGroupEnrollment, Reservation, LaneSet, User,
)
from app.schemas.schemas import (
    ClassCourseCreate, ClassCourseOut, ClassSessionOut, ClassEnrollmentOut,
    ClassGroupEnrollmentCreate, ClassGroupEnrollmentOut,
)
from app.utils.auth import get_current_user
from app.routers.reservations import _has_overlap, _reservation_lock

router = APIRouter(prefix="/class-courses", tags=["class-courses"])

_DAY_NAME_TO_WEEKDAY = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _require_admin(current_user: User):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="この操作には管理者権限が必要です")


def _enrolled_count(db: Session, course_id: int) -> int:
    return (
        db.query(ClassEnrollment)
        .filter(ClassEnrollment.course_id == course_id, ClassEnrollment.status == "enrolled")
        .count()
    )


@router.post("", response_model=ClassCourseOut, status_code=status.HTTP_201_CREATED)
def create_class_course(
    payload: ClassCourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    lane_set = db.query(LaneSet).filter(LaneSet.lane_set_id == payload.lane_set_id).first()
    if lane_set is None:
        raise HTTPException(status_code=404, detail="指定されたレーンセットが存在しません")
    if lane_set.status != "available":
        raise HTTPException(status_code=409, detail="このレーンセットは現在メンテナンス中です")

    # first_date の曜日が day_of_week と一致しているか確認
    expected_weekday = _DAY_NAME_TO_WEEKDAY[payload.day_of_week]
    if payload.first_date.weekday() != expected_weekday:
        raise HTTPException(
            status_code=422,
            detail=f"first_date の曜日が day_of_week（{payload.day_of_week}）と一致していません",
        )

    # session_count回分の日付を算出（7日おき）
    session_dates = [payload.first_date + timedelta(weeks=i) for i in range(payload.session_count)]

    with _reservation_lock:
        # 5回分すべてについて、事前に重複チェック（1件でも重複があれば全体を作らない）
        for d in session_dates:
            conflict = _has_overlap(
                db,
                filters=[Reservation.lane_set_id == payload.lane_set_id, Reservation.date == d],
                new_start=payload.start_time,
                new_end=payload.end_time,
            )
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail=f"E001: {d.isoformat()} の時間帯・レーンセットは既に予約されています。コースは作成されませんでした。",
                )

        course = ClassCourse(
            lane_set_id=payload.lane_set_id,
            day_of_week=payload.day_of_week,
            start_time=payload.start_time,
            end_time=payload.end_time,
            first_date=payload.first_date,
            session_count=payload.session_count,
            capacity=payload.capacity,
            instructor_name=payload.instructor_name,
            status="scheduled",
        )
        db.add(course)
        db.flush()  # course_id を確定させる

        for i, d in enumerate(session_dates, start=1):
            reservation = Reservation(
                user_id=current_user.user_id,
                lane_set_id=payload.lane_set_id,
                date=d,
                start_time=payload.start_time,
                end_time=payload.end_time,
                reservation_type="class",
                status="reserved",
            )
            db.add(reservation)

            session_row = ClassSession(
                course_id=course.course_id,
                session_number=i,
                date=d,
                start_time=payload.start_time,
                end_time=payload.end_time,
                status="scheduled",
            )
            db.add(session_row)

        db.commit()
        db.refresh(course)

    result = ClassCourseOut.model_validate(course)
    result.enrolled_count = 0
    return result


@router.get("", response_model=list[ClassCourseOut])
def list_class_courses(db: Session = Depends(get_db)):
    courses = db.query(ClassCourse).filter(ClassCourse.status == "scheduled").all()
    out = []
    for c in courses:
        item = ClassCourseOut.model_validate(c)
        item.enrolled_count = _enrolled_count(db, c.course_id)
        out.append(item)
    return out


@router.get("/{course_id}/sessions", response_model=list[ClassSessionOut])
def list_class_sessions(course_id: int, db: Session = Depends(get_db)):
    course = db.query(ClassCourse).filter(ClassCourse.course_id == course_id).first()
    if course is None:
        raise HTTPException(status_code=404, detail="コースが見つかりません")
    return (
        db.query(ClassSession)
        .filter(ClassSession.course_id == course_id)
        .order_by(ClassSession.session_number)
        .all()
    )


@router.post("/{course_id}/enroll", response_model=ClassEnrollmentOut, status_code=status.HTTP_201_CREATED)
def enroll_class_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    course = db.query(ClassCourse).filter(ClassCourse.course_id == course_id).first()
    if course is None:
        raise HTTPException(status_code=404, detail="コースが見つかりません")
    if course.status != "scheduled":
        raise HTTPException(status_code=409, detail="このコースは開講されていません")

    existing = (
        db.query(ClassEnrollment)
        .filter(
            ClassEnrollment.course_id == course_id,
            ClassEnrollment.user_id == current_user.user_id,
            ClassEnrollment.status == "enrolled",
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="既にこのコースに申し込み済みです")

    with _reservation_lock:
        if _enrolled_count(db, course_id) >= course.capacity:
            raise HTTPException(status_code=409, detail="このコースは定員に達しています")

        enrollment = ClassEnrollment(
            course_id=course_id,
            user_id=current_user.user_id,
            status="enrolled",
        )
        db.add(enrollment)
        db.commit()
        db.refresh(enrollment)
        return enrollment


@router.post("/{course_id}/enroll-group", response_model=ClassGroupEnrollmentOut, status_code=status.HTTP_201_CREATED)
def enroll_class_course_group(
    course_id: int,
    payload: ClassGroupEnrollmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """職場など、代表者がまとめて申し込む団体申込。人数上限なし（capacityのチェック対象外）。"""
    course = db.query(ClassCourse).filter(ClassCourse.course_id == course_id).first()
    if course is None:
        raise HTTPException(status_code=404, detail="コースが見つかりません")
    if course.status != "scheduled":
        raise HTTPException(status_code=409, detail="このコースは開講されていません")

    group_enrollment = ClassGroupEnrollment(
        course_id=course_id,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        headcount=payload.headcount,
        status="enrolled",
    )
    db.add(group_enrollment)
    db.commit()
    db.refresh(group_enrollment)
    return group_enrollment


@router.get("/{course_id}/group-enrollments", response_model=list[ClassGroupEnrollmentOut])
def list_group_enrollments(course_id: int, db: Session = Depends(get_db)):
    return (
        db.query(ClassGroupEnrollment)
        .filter(ClassGroupEnrollment.course_id == course_id, ClassGroupEnrollment.status == "enrolled")
        .all()
    )


@router.delete("/{course_id}/enroll", response_model=ClassEnrollmentOut)
def cancel_enrollment(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    enrollment = (
        db.query(ClassEnrollment)
        .filter(
            ClassEnrollment.course_id == course_id,
            ClassEnrollment.user_id == current_user.user_id,
            ClassEnrollment.status == "enrolled",
        )
        .first()
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="申込が見つかりません")

    enrollment.status = "cancelled"
    enrollment.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(enrollment)
    return enrollment
