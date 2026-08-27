"""
DBモデル定義

【第三弾拡張② 追記(コーチシフト管理×指導メモ)】
- 「シフト管理」は勤務スケジュール調整ではなく「教室コース/回への担当インストラクター割当」の意味。
- Instructor を新設。店舗スタッフ兼務(staff_id 経由でStaffに紐づく)/外部プロ/臨時の3種別に対応。
- ClassCourse.instructor_name(自由記述文字列)は廃止し、instructor_id(FK→Instructor)に置き換え。
- ClassSession に instructor_id(nullable、代打対応用)と session_note(開催回全体の運営メモ)を追加。
- ClassAttendance.absent_note は廃止し、ClassSession.session_note に統合。
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

    lane_set_id = Column(String(10), primary_key=True)
    name = Column(String(50), nullable=False)
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
    """教室コース全体（全5回セット）。
    【第三弾拡張②】instructor_name(自由記述文字列)を廃止し、instructor_id(FK)に置き換え。"""
    __tablename__ = "class_courses"

    course_id = Column(Integer, primary_key=True, autoincrement=True)
    lane_set_id = Column(String(10), ForeignKey("lane_sets.lane_set_id"), nullable=False, index=True)
    day_of_week = Column(String(10), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    first_date = Column(Date, nullable=False)
    session_count = Column(Integer, nullable=False, default=5)
    capacity = Column(Integer, nullable=False, default=10)
    instructor_id = Column(Integer, ForeignKey("instructors.id"), nullable=True)
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
    instructor = relationship("Instructor")


class ClassSession(Base):
    """コースから自動生成される各回（session_number 1〜N）。
    【第三弾拡張②】instructor_id(代打対応用、nullable)とsession_note(運営メモ)を追加。"""
    __tablename__ = "class_sessions"

    class_session_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("class_courses.course_id"), nullable=False, index=True)
    session_number = Column(Integer, nullable=False)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(String(20), nullable=False, default="scheduled")
    lane_pair = Column(Integer, nullable=True)
    instructor_id = Column(Integer, ForeignKey("instructors.id"), nullable=True)
    session_note = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('scheduled','cancelled')", name="ck_session_status"),
        CheckConstraint("end_time > start_time", name="ck_session_time_order"),
    )

    course = relationship("ClassCourse", back_populates="sessions")
    instructor = relationship("Instructor")


class ClassEnrollment(Base):
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
    __tablename__ = "group_reservation_details"

    detail_id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.reservation_id"), nullable=False, unique=True, index=True)
    contact_name = Column(String(100), nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    headcount = Column(Integer, nullable=True)

    reservation = relationship("Reservation")


class ClassGroupEnrollment(Base):
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


class Lane(Base):
    __tablename__ = "lanes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lane_set_id = Column(String(10), ForeignKey("lane_sets.lane_set_id"), nullable=False)
    lane_number = Column(Integer, nullable=False, unique=True)
    pair_number = Column(Integer, nullable=False)
    status = Column(Enum(LaneStatusEnum), default=LaneStatusEnum.available, nullable=False)
    notes = Column(Text, nullable=True)


class ClassAttendance(Base):
    """教室出欠。グループ単位で記録。
    【第三弾拡張②】absent_noteは廃止(ClassSession.session_noteに統合)。"""
    __tablename__ = "class_attendance"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    class_session_id = Column(Integer, ForeignKey("class_sessions.class_session_id"), nullable=False)
    attendance_status = Column(Enum(AttendanceStatusEnum), nullable=False)


class CheckIn(Base):
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
    __tablename__ = "pricing_rule"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    item_type = Column(Enum(ItemTypeEnum), nullable=False, unique=True)
    price = Column(Float, nullable=False)


class Staff(Base):
    """スタッフ管理。Userとは完全に別テーブル・別ドメイン。階層管理なし。"""
    __tablename__ = "staff"

    staff_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    pin_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())


class InstructorTypeEnum(str, enum.Enum):
    staff = "staff"
    external = "external"
    temporary = "temporary"


class Instructor(Base):
    """初心者教室のインストラクター(第三弾拡張②)。
    店舗スタッフ兼務の場合のみstaff_idでStaffと紐づく。外部プロ・臨時はStaffと独立に存在できる。"""
    __tablename__ = "instructors"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    instructor_type = Column(Enum(InstructorTypeEnum), nullable=False, default=InstructorTypeEnum.staff)
    staff_id = Column(Integer, ForeignKey("staff.staff_id"), nullable=True)
    contact_info = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    staff = relationship("Staff")
