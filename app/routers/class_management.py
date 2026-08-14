"""
class_management.py 修正版(3-2対応)

【3-2 ①】generate_class_sessions を廃止し、assign_lane_pair_to_sessions に変更:
  - class_courses.py のコース作成処理は既に5回分の ClassSession を生成しているため
    (既存の動作は変更しない)、本ファイルでの新規生成は行わない。
  - 代わりに、既にコース作成時点で生成済みの5セッションに対して lane_pair を
    一括UPDATEする処理に役割変更する。
  - start_time/end_time の再指定は不要(既存セッションのものをそのまま使うため)。

【3-2 ②】レーンアサイン変更API(update_session_lane_pair)を新規追加:
  - 個別セッション単位でlane_pairを変更する。
  - 「当日開放」「締切ベース開放」は今回のスコープ外(変更提案として保留)。

【修正4(3-1)】record_attendance は変更なし。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import (
    ClassCourse, ClassSession, ClassAttendance,
    ClassEnrollment, ClassGroupEnrollment, AttendanceStatusEnum,
)
from app.schemas.schemas import (
    ClassAttendanceCreate, ClassAttendanceRead,
    AssignLanePairRequest, AssignLanePairResponse,
    ClassSessionOut, LanePairUpdate,
)

router = APIRouter()


@router.post(
    "/class_courses/{course_id}/sessions/assign-lane-pair",
    response_model=AssignLanePairResponse,
    status_code=status.HTTP_200_OK,
)
def assign_lane_pair_to_sessions(
    course_id: int,
    payload: AssignLanePairRequest,
    db: Session = Depends(get_db),
):
    """コース作成時に既に生成済みの5セッションへ、lane_pairを一括設定・更新する。
    (3-1のgenerate_class_sessionsから役割変更。新規INSERTは行わない)"""
    course = db.query(ClassCourse).filter(ClassCourse.course_id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="教室コースが見つかりません")

    sessions = db.query(ClassSession).filter(ClassSession.course_id == course_id).all()
    if not sessions:
        raise HTTPException(
            status_code=404,
            detail="このコースにはセッションが存在しません(class_courses.py側のコース作成が未実施の可能性があります)",
        )

    for session in sessions:
        session.lane_pair = payload.lane_pair

    db.commit()
    return AssignLanePairResponse(
        message="対象セッションのlane_pairを更新しました",
        updated_count=len(sessions),
    )


@router.patch(
    "/class_sessions/{session_id}/lane-pair",
    response_model=ClassSessionOut,
)
def update_session_lane_pair(
    session_id: int,
    payload: LanePairUpdate,
    db: Session = Depends(get_db),
):
    """個別セッション単位でのレーンアサイン変更(3-2)。
    当日開放・締切ベース開放は今回のスコープ外(変更提案として別途保留)。"""
    session = db.query(ClassSession).filter(ClassSession.class_session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="教室セッションが見つかりません")

    session.lane_pair = payload.lane_pair
    db.commit()
    db.refresh(session)
    return session


@router.post("/class_sessions/{session_id}/attendance", response_model=ClassAttendanceRead)
def record_attendance(
    session_id: int,
    payload: ClassAttendanceCreate,
    db: Session = Depends(get_db),
):
    """教室グループ単位の出欠記録(全員出席/一部欠席継続/一部欠席スライド)"""
    session = db.query(ClassSession).filter(ClassSession.class_session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="教室セッションが見つかりません")

    if payload.attendance_status == AttendanceStatusEnum.partial_absent_slide:
        # スライド(振替)は職場グループ申込のコースのみ許可。
        # 既存 ClassEnrollment/ClassGroupEnrollment のテーブル・データは変更せず、
        # 参照のみで判定する。
        has_group_enrollment = (
            db.query(ClassGroupEnrollment)
            .filter(
                ClassGroupEnrollment.course_id == session.course_id,
                ClassGroupEnrollment.status == "enrolled",
            )
            .first()
            is not None
        )
        if not has_group_enrollment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="個人予約のコースでは振替(スライド)を選択できません。"
                       "「一部欠席・継続開催」を選んでください。",
            )

    attendance = ClassAttendance(
        class_session_id=session_id,
        attendance_status=payload.attendance_status,
        absent_note=payload.absent_note,
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance