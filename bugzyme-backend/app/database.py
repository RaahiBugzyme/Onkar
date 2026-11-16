
import os
import sys
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.db_safety import validate_test_database_url

load_dotenv()

_pytest_active = "pytest" in sys.modules
_test_mode = os.getenv("RAAHI_TEST_MODE") == "1"

if _pytest_active and not _test_mode:
    raise RuntimeError(
        "Pytest database access is disabled until backend/conftest.py validates "
        "TEST_DATABASE_URL. Do not set DATABASE_URL to bypass this guard."
    )

if _test_mode:
    try:
        _test_url = validate_test_database_url(
            os.getenv("TEST_DATABASE_URL"),
            application_fingerprint=os.getenv("RAAHI_APPLICATION_DATABASE_FINGERPRINT"),
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    DATABASE_URL = _test_url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = DATABASE_URL
else:
    DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
