"""
DB接続設定

- SQLiteを使用（PostgreSQL移行を見据え、SQLAlchemy ORM経由でアクセス）
- SQLiteはデフォルトで外部キー制約が無効なため、接続イベントで明示的にONにする
- 予約の排他制御のため、トランザクション分離レベルに注意（reservations.py参照）
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./bowling.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite接続ごとに外部キー制約を有効化する（デフォルトOFFのため必須）"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPIの依存性注入用DBセッション"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
