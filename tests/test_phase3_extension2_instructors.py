import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.models import Staff, User, LaneSet
from app.utils.staff_auth import hash_pin
from app.utils.auth import hash_password

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


@pytest.fixture(autouse=True)
def setup_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    staff = Staff(name="テストスタッフ", pin_hash=hash_pin("1234"), is_active=True)
    db.add(staff)

    admin_user = User(name="管理者", email="admin@example.com", password_hash=hash_password("password123"), role="admin")
    db.add(admin_user)

    # main.pyのseed処理は本番用DBファイルに対して実行され、テスト用インメモリDBには
    # 反映されないため、テストフィクスチャ側でLaneSetを明示的に用意する
    db.add(LaneSet(lane_set_id="A", name="Aセット（1・2番）", status="available"))

    db.commit()
    db.refresh(staff)
    db.refresh(admin_user)

    global STAFF_ID
    STAFF_ID = staff.staff_id

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def staff_headers():
    resp = client.post("/api/v1/staff/login", json={"pin_code": "1234"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def admin_user_token():
    resp = client.post("/auth/login", data={"username": "admin@example.com", "password": "password123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _create_course_via_api(headers_staff_login_not_needed=None, instructor_id=None):
    """コース作成はUser(admin)認証。ここではclass_courses.pyの仕様通りadmin userで作る。"""
    token = admin_user_token()
    headers = {"Authorization": f"Bearer {token}"}
    monday = _next_weekday(0)
    payload = {
        "lane_set_id": "A",
        "day_of_week": "monday",
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "first_date": monday.isoformat(),
        "session_count": 5,
        "capacity": 10,
    }
    if instructor_id is not None:
        payload["instructor_id"] = instructor_id
    resp = client.post("/class-courses", json=payload, headers=headers)
    return resp


# --- Instructor CRUD ---

def test_create_instructor_staff_type_requires_staff_id():
    headers = staff_headers()
    resp = client.post(
        "/api/v1/instructors",
        json={"name": "山田コーチ", "instructor_type": "staff"},
        headers=headers,
    )
    assert resp.status_code == 422  # staff_id必須のバリデーション


def test_create_instructor_staff_type_with_valid_staff_id():
    headers = staff_headers()
    resp = client.post(
        "/api/v1/instructors",
        json={"name": "山田コーチ", "instructor_type": "staff", "staff_id": STAFF_ID},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["staff_id"] == STAFF_ID


def test_create_instructor_external_type_without_staff_id():
    headers = staff_headers()
    resp = client.post(
        "/api/v1/instructors",
        json={"name": "外部プロ鈴木", "instructor_type": "external", "contact_info": "suzuki@example.com"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["staff_id"] is None


def test_create_instructor_external_type_with_staff_id_rejected():
    """外部プロなのにstaff_idを指定するのは矛盾なので拒否される"""
    headers = staff_headers()
    resp = client.post(
        "/api/v1/instructors",
        json={"name": "矛盾ケース", "instructor_type": "external", "staff_id": STAFF_ID},
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_instructor_requires_staff_auth():
    resp = client.post("/api/v1/instructors", json={"name": "無認証", "instructor_type": "external"})
    assert resp.status_code == 401


def test_list_instructors():
    headers = staff_headers()
    client.post(
        "/api/v1/instructors",
        json={"name": "臨時田中", "instructor_type": "temporary"},
        headers=headers,
    )
    resp = client.get("/api/v1/instructors", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --- コースへのインストラクター割当 ---

def test_assign_instructor_to_course_and_course_out_resolves_name():
    headers = staff_headers()
    resp_inst = client.post(
        "/api/v1/instructors",
        json={"name": "田中コーチ", "instructor_type": "staff", "staff_id": STAFF_ID},
        headers=headers,
    )
    instructor_id = resp_inst.json()["id"]

    resp_course = _create_course_via_api()
    assert resp_course.status_code == 201
    course_id = resp_course.json()["course_id"]
    # 作成直後はinstructor未割当
    assert resp_course.json()["instructor_name"] is None

    resp_assign = client.patch(
        f"/api/v1/instructors/class-courses/{course_id}/instructor",
        json={"instructor_id": instructor_id},
        headers=headers,
    )
    assert resp_assign.status_code == 200
    assert resp_assign.json()["instructor_name"] == "田中コーチ"

    # 一覧側でも解決されていること(第二弾のフロント表示互換確認)
    resp_list = client.get("/class-courses")
    course_in_list = [c for c in resp_list.json() if c["course_id"] == course_id][0]
    assert course_in_list["instructor_name"] == "田中コーチ"


def test_assign_instructor_unknown_course_404():
    headers = staff_headers()
    resp_inst = client.post(
        "/api/v1/instructors",
        json={"name": "テスト", "instructor_type": "external"},
        headers=headers,
    )
    instructor_id = resp_inst.json()["id"]

    resp = client.patch(
        "/api/v1/instructors/class-courses/99999/instructor",
        json={"instructor_id": instructor_id},
        headers=headers,
    )
    assert resp.status_code == 404


def test_assign_unknown_instructor_to_course_404():
    headers = staff_headers()
    resp_course = _create_course_via_api()
    course_id = resp_course.json()["course_id"]

    resp = client.patch(
        f"/api/v1/instructors/class-courses/{course_id}/instructor",
        json={"instructor_id": 99999},
        headers=headers,
    )
    assert resp.status_code == 404


# --- セッション単位の代打対応 ---

def test_session_instructor_override_for_substitute():
    headers = staff_headers()
    resp_inst1 = client.post(
        "/api/v1/instructors",
        json={"name": "通常担当", "instructor_type": "staff", "staff_id": STAFF_ID},
        headers=headers,
    )
    instructor1_id = resp_inst1.json()["id"]
    resp_inst2 = client.post(
        "/api/v1/instructors",
        json={"name": "代打外部プロ", "instructor_type": "external"},
        headers=headers,
    )
    instructor2_id = resp_inst2.json()["id"]

    resp_course = _create_course_via_api(instructor_id=instructor1_id)
    course_id = resp_course.json()["course_id"]

    resp_sessions = client.get(f"/class-courses/{course_id}/sessions")
    session_id = resp_sessions.json()[0]["class_session_id"]
    # コース作成直後、セッション側のinstructor_idはまだ設定されていない(コース側を継承する想定)
    assert resp_sessions.json()[0]["instructor_id"] is None

    resp_override = client.patch(
        f"/api/v1/class_sessions/{session_id}/instructor",
        json={"instructor_id": instructor2_id},
        headers=headers,
    )
    assert resp_override.status_code == 200
    assert resp_override.json()["instructor_id"] == instructor2_id

    # Noneで上書き解除できる
    resp_clear = client.patch(
        f"/api/v1/class_sessions/{session_id}/instructor",
        json={"instructor_id": None},
        headers=headers,
    )
    assert resp_clear.status_code == 200
    assert resp_clear.json()["instructor_id"] is None


def test_session_instructor_override_unknown_instructor_404():
    headers = staff_headers()
    resp_course = _create_course_via_api()
    course_id = resp_course.json()["course_id"]
    session_id = client.get(f"/class-courses/{course_id}/sessions").json()[0]["class_session_id"]

    resp = client.patch(
        f"/api/v1/class_sessions/{session_id}/instructor",
        json={"instructor_id": 99999},
        headers=headers,
    )
    assert resp.status_code == 404


# --- session_note ---

def test_update_session_note():
    headers = staff_headers()
    resp_course = _create_course_via_api()
    course_id = resp_course.json()["course_id"]
    session_id = client.get(f"/class-courses/{course_id}/sessions").json()[0]["class_session_id"]

    resp = client.patch(
        f"/api/v1/class_sessions/{session_id}/note",
        json={"session_note": "レーンコンディション不良のため進行が遅れた"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["session_note"] == "レーンコンディション不良のため進行が遅れた"


def test_update_session_note_unknown_session_404():
    headers = staff_headers()
    resp = client.patch(
        "/api/v1/class_sessions/99999/note",
        json={"session_note": "test"},
        headers=headers,
    )
    assert resp.status_code == 404


# --- ClassAttendanceからabsent_noteが完全に削除されていること ---

def test_class_attendance_schema_has_no_absent_note_field():
    """absent_noteフィールドが完全に廃止されていることの回帰防止テスト"""
    headers = staff_headers()
    resp_course = _create_course_via_api()
    course_id = resp_course.json()["course_id"]
    session_id = client.get(f"/class-courses/{course_id}/sessions").json()[0]["class_session_id"]

    resp = client.post(
        f"/api/v1/class_sessions/{session_id}/attendance",
        json={"class_session_id": session_id, "attendance_status": "all_present"},
    )
    assert resp.status_code == 200
    assert "absent_note" not in resp.json()


def test_class_attendance_with_absent_note_field_is_ignored_not_erroring():
    """クライアントが古いスキーマ通りabsent_noteを送っても、余分なフィールドとして
    無視される(Pydanticのデフォルト動作、エラーにはならない)ことを確認"""
    headers = staff_headers()
    resp_course = _create_course_via_api()
    course_id = resp_course.json()["course_id"]
    session_id = client.get(f"/class-courses/{course_id}/sessions").json()[0]["class_session_id"]

    resp = client.post(
        f"/api/v1/class_sessions/{session_id}/attendance",
        json={
            "class_session_id": session_id,
            "attendance_status": "partial_absent_continue",
            "absent_note": "旧スキーマ互換確認用",
        },
    )
    assert resp.status_code == 200
    assert "absent_note" not in resp.json()
