"""
DBモデル定義

設計方針（レビューで確定した内容）：
- Users.role: user / competitor / admin（要件定義Ver.2準拠）
- LaneSet: MVPではセット単位の状態管理のみ（個別レーン管理はPhase2）
- Reservation: reservation_type（システム区分）のみMVP対象。purposeは対象外
- status は論理削除方式（reserved / cancelled）。物理削除は行わない

【第三弾 Phase3-1 追記】
- User と staff（別ファイル app/models/staff.py）は別テーブル
- LaneSet は変更せず維持。個別レーン管理は本ファイル末尾の Lane で追加
- ClassSession は置き換えず拡張（lane_pair カラムを追加）
- class_group は新設しない。ClassCourse / ClassEnrollment / ClassGroupEnrollment で代替
- lane_pair は先頭レーン番号方式（1→1・2番, 3→3・4番, 5→5・6番）
"""
import enum
from sqlalchemy import (
    Column, Integer, String, Date, Time, ForeignKey,
    CheckConstraint, DateTime, func, Boolean, Float, Enum, Text
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('user','competitor','admin')", name="ck_users_role"),
    )

    reservations = relationship("Reservation", back_populates="user")


class LaneSet(Base):
    __tablename__ = "lane_sets"

    # 例: 'A', 'B'
    lane_set_id = Column(String(10), primary_key=True)
    name = Column(String(50), nullable=False)
    # MVPではセット単位の状態管理のみ（個別レーンの故障管理はPhase2で Lanes テーブルを分離）
    status = Column(String(20), nullable=False, default="available")

    __table_args__ = (
        CheckConstraint("status IN ('available','maintenance')", name="ck_lanesets_status"),
    )

    reservations = relationship("Reservation", back_populates="lane_set")


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    lane_set_id = Column(String(10), ForeignKey("lane_sets.lane_set_id"), nullable=False, index=True)

    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    # システム管理用区分。class(初心者教室)は将来拡張だが値としては予約しておく
    reservation_type = Column(String(30), nullable=False, default="general")
    status = Column(String(20), nullable=False, default="reserved")

    created_at = Column(DateTime, server_default=func.now())
    cancelled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("reservation_type IN ('general','practice','class','group')", name="ck_res_type"),
        CheckConstraint("status IN ('reserved','cancelled')", name="ck_res_status"),
        CheckConstraint("end_time > start_time", name="ck_res_time_order"),
    )

    user = relationship("User", back_populates="reservations")
    lane_set = relationship("LaneSet", back_populates="reservations")


class ClassCourse(Base):
    """教室コース全体（全5回セット）。第二弾で追加。"""
    __tablename__ = "class_courses"

    course_id = Column(Integer, primary_key=True, autoincrement=True)
    lane_set_id = Column(String(10), ForeignKey("lane_sets.lane_set_id"), nullable=False, index=True)
    day_of_week = Column(String(10), nullable=False)  # 'monday'...'sunday'
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    first_date = Column(Date, nullable=False)
    session_count = Column(Integer, nullable=False, default=5)
    capacity = Column(Integer, nullable=False, default=10)
    instructor_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="scheduled")

    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_course_capacity"),
        CheckConstraint("session_count > 0", name="ck_course_session_count"),
        CheckConstraint("status IN ('scheduled','cancelled')", name="ck_course_status"),
        CheckConstraint("end_time > start_time", name="ck_course_time_order"),
    )

    lane_set = relationship("LaneSet")
    sessions = relationship("ClassSession", back_populates="course")
    enrollments = relationship("ClassEnrollment", back_populates="course")


class ClassSession(Base):
    """コースから自動生成される各回（session_number 1〜N）。第二弾で追加。
    【第三弾で拡張】lane_pair を追加（先頭レーン番号方式）。既存カラムは変更なし。"""
    __tablename__ = "class_sessions"

    class_session_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("class_courses.course_id"), nullable=False, index=True)
    session_number = Column(Integer, nullable=False)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(String(20), nullable=False, default="scheduled")
    lane_pair = Column(Integer, nullable=True)  # 追加分: 1→1・2番, 3→3・4番, 5→5・6番

    __table_args__ = (
        CheckConstraint("status IN ('scheduled','cancelled')", name="ck_session_status"),
        CheckConstraint("end_time > start_time", name="ck_session_time_order"),
    )

    course = relationship("ClassCourse", back_populates="sessions")


class ClassEnrollment(Base):
    """生徒の申込。コース単位（1回申込で全セッション分参加扱い）。第二弾で追加。"""
    __tablename__ = "class_enrollments"

    enrollment_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("class_courses.course_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="enrolled")
    created_at = Column(DateTime, server_default=func.now())
    cancelled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('enrolled','cancelled')", name="ck_enrollment_status"),
    )

    course = relationship("ClassCourse", back_populates="enrollments")
    user = relationship("User")


class GroupReservationDetail(Base):
    """クラウドファンディング特典（レーン貸し切り等）用の予約追加情報。
    教室・団体練習とは無関係の、特典利用者向けレーン貸し切り予約。第二弾で追加。"""
    __tablename__ = "group_reservation_details"

    detail_id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.reservation_id"), nullable=False, unique=True, index=True)
    contact_name = Column(String(100), nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    headcount = Column(Integer, nullable=True)

    reservation = relationship("Reservation")


class ClassGroupEnrollment(Base):
    """教室コースへの団体申込（職場単位など）。人数上限なし。第二弾で追加。
    個人申込(ClassEnrollment)とは別枠で扱い、定員(capacity)のチェック対象にしない。"""
    __tablename__ = "class_group_enrollments"

    group_enrollment_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("class_courses.course_id"), nullable=False, index=True)
    contact_name = Column(String(100), nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    headcount = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="enrolled")
    created_at = Column(DateTime, server_default=func.now())
    cancelled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('enrolled','cancelled')", name="ck_group_enrollment_status"),
    )

    course = relationship("ClassCourse")


# =====================================================================
# 【第三弾 Phase3-1 新規追加】
# =====================================================================

# --- Enum定義 ---

class LaneStatusEnum(str, enum.Enum):
    available = "available"
    in_use = "in_use"
    broken = "broken"
    maintenance = "maintenance"


class CheckInStatusEnum(str, enum.Enum):
    checked_in = "checked_in"
    in_use = "in_use"
    checked_out = "checked_out"


class AttendanceStatusEnum(str, enum.Enum):
    all_present = "all_present"
    partial_absent_continue = "partial_absent_continue"
    partial_absent_slide = "partial_absent_slide"


class PayerTypeEnum(str, enum.Enum):
    # 修正: 「class_group」テーブルは新設しない方針のため、メンバー名を course に変更
    # (値"class"自体は憲法7章の確定値のまま変更なし)
    course = "class"
    checkin = "checkin"


class PaymentTimingEnum(str, enum.Enum):
    prepaid = "prepaid"
    postpaid = "postpaid"


class PaymentMethodEnum(str, enum.Enum):
    cash = "cash"
    card = "card"
    e_payment = "e_payment"
    unpaid = "unpaid"


class ItemTypeEnum(str, enum.Enum):
    lane_time = "lane_time"
    shoes_rental = "shoes_rental"
    ball_rental = "ball_rental"
    class_fee = "class"


# --- 新規モデルクラス ---

class Lane(Base):
    """個別レーン管理。既存 LaneSet は変更せず維持し、lane_set_id で紐付ける。"""
    __tablename__ = "lanes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lane_set_id = Column(String(10), ForeignKey("lane_sets.lane_set_id"), nullable=False)
    lane_number = Column(Integer, nullable=False, unique=True)
    pair_number = Column(Integer, nullable=False)  # ペア識別番号 (1番,2番->1 / 3番,4番->2)
    status = Column(Enum(LaneStatusEnum), default=LaneStatusEnum.available, nullable=False)
    notes = Column(Text, nullable=True)


class ClassAttendance(Base):
    """教室出欠。既存 class_sessions.class_session_id にFK。グループ単位で記録。"""
    __tablename__ = "class_attendance"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    class_session_id = Column(Integer, ForeignKey("class_sessions.class_session_id"), nullable=False)
    attendance_status = Column(Enum(AttendanceStatusEnum), nullable=False)
    absent_note = Column(Text, nullable=True)


class CheckIn(Base):
    """来店受付・利用管理。"""
    __tablename__ = "checkin"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.reservation_id"), nullable=True)
    lane_id = Column(Integer, ForeignKey("lanes.id"), nullable=False)
    status = Column(Enum(CheckInStatusEnum), default=CheckInStatusEnum.checked_in, nullable=False)
    checkin_time = Column(DateTime, nullable=False)
    checkout_time = Column(DateTime, nullable=True)
    is_trial = Column(Boolean, default=False, nullable=False)
    shoes_rental = Column(Boolean, default=False, nullable=False)
    ball_rental = Column(Boolean, default=False, nullable=False)


class Payment(Base):
    """決済。payer_type=course のとき course_id、checkin のとき checkin_id を使用。"""
    __tablename__ = "payment"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    payer_type = Column(Enum(PayerTypeEnum), nullable=False)
    course_id = Column(Integer, ForeignKey("class_courses.course_id"), nullable=True)
    checkin_id = Column(Integer, ForeignKey("checkin.id"), nullable=True)
    payment_timing = Column(Enum(PaymentTimingEnum), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(Enum(PaymentMethodEnum), default=PaymentMethodEnum.unpaid, nullable=False)
    is_paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime, nullable=True)


class PricingRule(Base):
    """料金マスタ。時間単価制(1ゲーム単位ではない)。"""
    __tablename__ = "pricing_rule"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    item_type = Column(Enum(ItemTypeEnum), nullable=False, unique=True)
    price = Column(Float, nullable=False)


class Staff(Base):
    """スタッフ管理(グループC・Claude担当)。
    Userとは完全に別テーブル・別ドメイン(お客様認証 vs スタッフ認証)。
    pin_codeは平文で保持せず、bcryptハッシュ化してpin_hashに保持する
    (既存Userのpassword_hashと同じ設計思想に統一)。
    階層管理なし(role等のカラムを持たない)。少人数運営・簡易PIN認証の方針。
    コーチのシフト管理(coach_shift等)はPhase3-2のため本ファイルには含まない。
    """
    __tablename__ = "staff"

    staff_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    pin_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
