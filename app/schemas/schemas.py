"""
Pydanticスキーマ（API境界のバリデーション）
"""
from datetime import date, time, datetime
from typing import Optional, List
from zoneinfo import ZoneInfo
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator, model_validator

from app.models.models import (
    LaneStatusEnum, CheckInStatusEnum, AttendanceStatusEnum,
    PayerTypeEnum, PaymentTimingEnum, PaymentMethodEnum, ItemTypeEnum,
    InstructorTypeEnum,
)

JST = ZoneInfo("Asia/Tokyo")


# ---------- User ----------

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "user"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ("user", "competitor", "admin"):
            raise ValueError("role must be one of: user, competitor, admin")
        return v


class UserOut(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    role: str

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Reservation ----------

class ReservationCreate(BaseModel):
    lane_set_id: str
    date: date
    start_time: time
    end_time: time
    reservation_type: str = "general"

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_30min_unit(cls, v: time):
        if v.minute not in (0, 30) or v.second != 0:
            raise ValueError("予約時間は30分単位で指定してください（例: 10:00, 10:30）")
        return v

    @field_validator("reservation_type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("general", "practice", "class", "group"):
            raise ValueError("reservation_type must be one of: general, practice, class, group")
        return v

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @model_validator(mode="after")
    def validate_not_past(self):
        reservation_start = datetime.combine(self.date, self.start_time, tzinfo=JST)
        if reservation_start < datetime.now(JST):
            raise ValueError("過去の日時には予約できません")
        return self


class ReservationOut(BaseModel):
    reservation_id: int
    user_id: int
    lane_set_id: str
    date: date
    start_time: time
    end_time: time
    reservation_type: str
    status: str
    created_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReservationUpdate(BaseModel):
    lane_set_id: Optional[str] = None
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_30min_unit(cls, v: Optional[time]):
        if v is None:
            return v
        if v.minute not in (0, 30) or v.second != 0:
            raise ValueError("予約時間は30分単位で指定してください（例: 10:00, 10:30）")
        return v


# ---------- LaneSet ----------

class LaneSetOut(BaseModel):
    lane_set_id: str
    name: str
    status: str

    class Config:
        from_attributes = True


class LaneSetStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in ("available", "maintenance"):
            raise ValueError("status must be 'available' or 'maintenance'")
        return v


# ---------- Instructor（第三弾拡張②：新設） ----------

class InstructorCreate(BaseModel):
    name: str
    instructor_type: InstructorTypeEnum = InstructorTypeEnum.staff
    staff_id: Optional[int] = None  # 店舗スタッフ兼務の場合のみ指定
    contact_info: Optional[str] = None

    @model_validator(mode="after")
    def validate_staff_id_consistency(self):
        # 店舗スタッフ兼務(staff)の場合のみ staff_id を必須とする。
        # 外部プロ・臨時は Staff と無関係に存在できるため staff_id を持たせない。
        if self.instructor_type == InstructorTypeEnum.staff and self.staff_id is None:
            raise ValueError("instructor_type='staff' の場合、staff_id の指定が必要です")
        if self.instructor_type != InstructorTypeEnum.staff and self.staff_id is not None:
            raise ValueError("instructor_type='staff' 以外では staff_id を指定できません")
        return self


class InstructorOut(BaseModel):
    id: int
    name: str
    instructor_type: InstructorTypeEnum
    staff_id: Optional[int] = None
    contact_info: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class InstructorActiveUpdate(BaseModel):
    is_active: bool


class CourseInstructorAssign(BaseModel):
    """コース単位でのインストラクター割当（第三弾拡張②の中心機能）"""
    instructor_id: int


class SessionInstructorAssign(BaseModel):
    """開催回単位での担当上書き（代打対応）。Noneを指定するとコースの担当に戻す。"""
    instructor_id: Optional[int] = None


class SessionNoteUpdate(BaseModel):
    """開催回全体の運営メモ更新（欠席理由・スライド判断・代打対応等を集約）"""
    session_note: Optional[str] = None


# ---------- ClassCourse ----------

class ClassCourseCreate(BaseModel):
    lane_set_id: str
    day_of_week: str
    start_time: time
    end_time: time
    first_date: date
    session_count: int = 5
    capacity: int = 10
    instructor_id: Optional[int] = None  # 第三弾拡張②: instructor_name(文字列)から置き換え

    @field_validator("day_of_week")
    @classmethod
    def validate_day_of_week(cls, v):
        valid_days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        if v not in valid_days:
            raise ValueError(f"day_of_week must be one of: {', '.join(valid_days)}")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_30min_unit(cls, v: time):
        if v.minute not in (0, 30) or v.second != 0:
            raise ValueError("予約時間は30分単位で指定してください（例: 10:00, 10:30）")
        return v

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @field_validator("first_date")
    @classmethod
    def validate_not_past(cls, v: date):
        if v < date.today():
            raise ValueError("過去の日付には予約できません")
        return v

    @field_validator("session_count")
    @classmethod
    def validate_session_count(cls, v):
        if v <= 0:
            raise ValueError("session_count must be greater than 0")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v):
        if v <= 0:
            raise ValueError("capacity must be greater than 0")
        return v


class ClassCourseOut(BaseModel):
    course_id: int
    lane_set_id: str
    day_of_week: str
    start_time: time
    end_time: time
    first_date: date
    session_count: int
    capacity: int
    instructor_id: Optional[int] = None
    instructor_name: Optional[str] = None  # 第二弾向け表示用。Instructorから解決してルーター側で埋める
    status: str
    enrolled_count: Optional[int] = None

    class Config:
        from_attributes = True


# ---------- ClassSession ----------

class ClassSessionOut(BaseModel):
    class_session_id: int
    course_id: int
    session_number: int
    date: date
    start_time: time
    end_time: time
    status: str
    lane_pair: Optional[int] = None
    instructor_id: Optional[int] = None  # 第三弾拡張②
    session_note: Optional[str] = None  # 第三弾拡張②

    class Config:
        from_attributes = True


class ClassSessionStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in ("scheduled", "cancelled"):
            raise ValueError("status must be 'scheduled' or 'cancelled'")
        return v


# ---------- ClassEnrollment ----------

class ClassEnrollmentCreate(BaseModel):
    course_id: int


class ClassEnrollmentOut(BaseModel):
    enrollment_id: int
    course_id: int
    user_id: int
    status: str
    created_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Group Reservation ----------

class GroupReservationCreate(BaseModel):
    lane_set_id: str
    date: date
    start_time: time
    end_time: time
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    headcount: Optional[int] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_30min_unit(cls, v: time):
        if v.minute not in (0, 30) or v.second != 0:
            raise ValueError("予約時間は30分単位で指定してください（例: 10:00, 10:30）")
        return v

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @field_validator("date")
    @classmethod
    def validate_not_past(cls, v: date):
        if v < date.today():
            raise ValueError("過去の日付には予約できません")
        return v

    @field_validator("headcount")
    @classmethod
    def validate_headcount(cls, v):
        if v is not None and v <= 0:
            raise ValueError("headcount must be greater than 0")
        return v


class GroupReservationOut(BaseModel):
    reservation_id: int
    lane_set_id: str
    date: date
    start_time: time
    end_time: time
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    headcount: Optional[int] = None
    status: str

    class Config:
        from_attributes = True


# ---------- ClassGroupEnrollment ----------

class ClassGroupEnrollmentCreate(BaseModel):
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    headcount: Optional[int] = None

    @field_validator("headcount")
    @classmethod
    def validate_headcount(cls, v):
        if v is not None and v <= 0:
            raise ValueError("headcount must be greater than 0")
        return v


class ClassGroupEnrollmentOut(BaseModel):
    group_enrollment_id: int
    course_id: int
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    headcount: Optional[int] = None
    status: str
    created_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Lane ----------

class LaneBase(BaseModel):
    lane_set_id: str
    lane_number: int
    pair_number: int
    status: LaneStatusEnum = LaneStatusEnum.available
    notes: Optional[str] = None


class LaneStatusUpdateP3(BaseModel):
    status: LaneStatusEnum
    notes: Optional[str] = None


class LaneRead(LaneBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- ClassAttendance ----------

class ClassAttendanceCreate(BaseModel):
    """第三弾拡張②: absent_noteは廃止(ClassSession.session_noteに統合したため)"""
    class_session_id: int
    attendance_status: AttendanceStatusEnum


class ClassAttendanceRead(ClassAttendanceCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- レーンアサイン変更 ----------

class LanePairUpdate(BaseModel):
    lane_pair: int

    @field_validator("lane_pair")
    @classmethod
    def validate_lane_pair(cls, v):
        if v < 1 or v % 2 == 0:
            raise ValueError("lane_pair must be an odd number representing the first lane of a pair (1, 3, 5...)")
        return v


class AssignLanePairRequest(BaseModel):
    lane_pair: int

    @field_validator("lane_pair")
    @classmethod
    def validate_lane_pair(cls, v):
        if v < 1 or v % 2 == 0:
            raise ValueError("lane_pair must be an odd number representing the first lane of a pair (1, 3, 5...)")
        return v


class AssignLanePairResponse(BaseModel):
    message: str
    updated_count: int


# ---------- CheckIn ----------

class CheckInCreate(BaseModel):
    reservation_id: Optional[int] = None
    lane_id: int
    is_trial: bool = False
    shoes_rental: bool = False
    ball_rental: bool = False


class CheckInStatusUpdate(BaseModel):
    status: CheckInStatusEnum


class CheckInRead(BaseModel):
    id: int
    reservation_id: Optional[int]
    lane_id: int
    status: CheckInStatusEnum
    checkin_time: datetime
    checkout_time: Optional[datetime]
    is_trial: bool
    shoes_rental: bool
    ball_rental: bool
    model_config = ConfigDict(from_attributes=True)


# ---------- Payment ----------

class PaymentCreate(BaseModel):
    payer_type: PayerTypeEnum
    course_id: Optional[int] = None
    checkin_id: Optional[int] = None
    payment_timing: PaymentTimingEnum
    amount: float
    payment_method: PaymentMethodEnum = PaymentMethodEnum.unpaid
    is_paid: bool = False


class PaymentPay(BaseModel):
    payment_method: PaymentMethodEnum


class PaymentRead(BaseModel):
    id: int
    payer_type: PayerTypeEnum
    course_id: Optional[int]
    checkin_id: Optional[int]
    payment_timing: PaymentTimingEnum
    amount: float
    payment_method: PaymentMethodEnum
    is_paid: bool
    paid_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


class PricingCalculateRequest(BaseModel):
    lane_id: int
    duration_hours: float
    shoes_rental_count: int = 0
    ball_rental_count: int = 0


class PricingCalculateResponse(BaseModel):
    lane_fee: float
    shoes_fee: float
    ball_fee: float
    total_amount: float


class PricingRuleRead(BaseModel):
    id: int
    item_type: ItemTypeEnum
    price: float
    model_config = ConfigDict(from_attributes=True)


# ---------- Dashboard ----------

class DashboardReservationRead(BaseModel):
    reservation_id: int
    user_id: int
    lane_set_id: str
    start_time: str
    end_time: str
    status: str


class DashboardClassSessionRead(BaseModel):
    class_session_id: int
    course_id: int
    session_number: int
    start_time: str
    end_time: str
    lane_pair: Optional[int]
    status: str


class DashboardResponse(BaseModel):
    lanes: List[LaneRead]
    today_reservations: List[DashboardReservationRead]
    today_class_sessions: List[DashboardClassSessionRead]


# ---------- Staff ----------

class StaffCreate(BaseModel):
    name: str
    pin_code: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("pin_code")
    @classmethod
    def validate_pin_code(cls, v):
        if not (v.isdigit() and len(v) == 4):
            raise ValueError("pin_code must be exactly 4 digits")
        return v


class StaffOut(BaseModel):
    staff_id: int
    name: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StaffLogin(BaseModel):
    pin_code: str

    @field_validator("pin_code")
    @classmethod
    def validate_pin_code(cls, v):
        if not (v.isdigit() and len(v) == 4):
            raise ValueError("pin_code must be exactly 4 digits")
        return v


class StaffActiveUpdate(BaseModel):
    is_active: bool


class StaffToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
