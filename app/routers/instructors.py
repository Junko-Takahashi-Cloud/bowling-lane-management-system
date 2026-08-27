"""
インストラクター管理・コース担当割当エンドポイント(第三弾拡張②)

設計方針:
- 「コーチシフト管理」は勤務スケジュール調整ではなく、教室コース/回への
  担当インストラクター割当という意味で実装する。
- Instructor は Staff とは独立した実体。店舗スタッフ兼務のみ staff_id で紐づく。
- スタッフ認証(get_current_staff)で保護する。第三弾は階層管理がないため、
  ログイン済みスタッフなら誰でも操作可能(既存staff.pyの設計方針を踏襲)。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Instructor, Staff, ClassCourse, InstructorTypeEnum
from app.schemas.schemas import (
    InstructorCreate, InstructorOut, InstructorActiveUpdate,
    CourseInstructorAssign, ClassCourseOut,
)
from app.utils.staff_auth import get_current_staff
from app.routers.class_courses import _to_course_out

router = APIRouter(prefix="/api/v1/instructors", tags=["instructors"])


@router.post("", response_model=InstructorOut, status_code=status.HTTP_201_CREATED)
def create_instructor(
    payload: InstructorCreate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    if payload.staff_id is not None:
        staff = db.query(Staff).filter(Staff.staff_id == payload.staff_id).first()
        if not staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたスタッフが見つかりません")

    instructor = Instructor(
        name=payload.name,
        instructor_type=payload.instructor_type,
        staff_id=payload.staff_id,
        contact_info=payload.contact_info,
        is_active=True,
    )
    db.add(instructor)
    db.commit()
    db.refresh(instructor)
    return instructor


@router.get("", response_model=list[InstructorOut])
def list_instructors(
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    return db.query(Instructor).filter(Instructor.is_active == True).all()  # noqa: E712


@router.patch("/{instructor_id}/active", response_model=InstructorOut)
def update_instructor_active(
    instructor_id: int,
    payload: InstructorActiveUpdate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    instructor = db.query(Instructor).filter(Instructor.id == instructor_id).first()
    if not instructor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="インストラクターが見つかりません")
    instructor.is_active = payload.is_active
    db.commit()
    db.refresh(instructor)
    return instructor


@router.patch("/class-courses/{course_id}/instructor", response_model=ClassCourseOut)
def assign_instructor_to_course(
    course_id: int,
    payload: CourseInstructorAssign,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
):
    """コース単位でのインストラクター割当(第三弾拡張②の中心機能)。
    5回とも同じ担当が基本のケースをここで設定し、代打が必要な回だけ
    class_management.py の update_session_instructor で個別に上書きする。"""
    course = db.query(ClassCourse).filter(ClassCourse.course_id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="コースが見つかりません")

    instructor = db.query(Instructor).filter(Instructor.id == payload.instructor_id).first()
    if not instructor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたインストラクターが見つかりません")

    course.instructor_id = payload.instructor_id
    db.commit()
    db.refresh(course)
    return _to_course_out(db, course)
