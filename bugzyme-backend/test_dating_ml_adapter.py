import hashlib
import json
from datetime import date
from pathlib import Path

from app import models
from app.database import SessionLocal
from app.services.dating_ml_adapter import DatingMLAdapter, map_raahi_profile
from app.services.dating_ml_model import CompatibilityModel
from app.services import dating_ml_model


def test_package_import_and_public_api():
    assert dating_ml_model.__version__ == "2.2.0"
    model = CompatibilityModel()
    assert callable(model.predict_pair)
    assert callable(model.check_eligibility)


def test_copied_package_matches_authoritative_manifest():
    manifest_path = Path(__file__).with_name("dating_ml_model.source_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    package = Path(__file__).parent / "app" / "services" / "dating_ml_model"
    actual = {
        p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    assert actual == manifest


def test_raahi_profile_mapping_keeps_unavailable_model_fields_unknown():
    profile = models.UserProfile(
        user_id=777, date_of_birth=date(1990, 5, 4), gender="other", city="Pune",
        era="millennial", vibe_tag=None,
    )
    mapped = map_raahi_profile(profile, reference_date=date(2026, 11, 12))
    assert mapped["age"] == 36
    assert mapped["birth_year"] == 1990
    assert mapped["sex"] is None
    assert mapped["orientation"] is None
    assert mapped["education"] is None
    assert mapped["vibe_tag"] is None


def test_missing_orientation_preserves_model_ineligibility_and_none_scores():
    model = CompatibilityModel()
    first = {"id": "a", "age": 30, "sex": "female", "orientation": None}
    second = {"id": "b", "age": 31, "sex": "male", "orientation": None}
    result = model.predict_pair(first, second)
    assert result["eligible"] is False
    assert result["compatibility_score"] is None
    assert result["confidence_score"] is None
    assert result["adjusted_score"] is None


def test_compatibility_confidence_version_components_and_explanations_are_separate():
    model = CompatibilityModel()
    first = {"id": "a", "age": 30, "sex": "female", "orientation": "straight", "education": "college"}
    second = {"id": "b", "age": 31, "sex": "male", "orientation": "straight", "education": "college"}
    result = model.predict_pair(first, second)
    assert result["eligible"] is True
    assert isinstance(result["compatibility_score"], float)
    assert isinstance(result["confidence_score"], float)
    assert "adjusted_score" in result and "components" in result and "explanation" in result
    assert result["model_version"] == model.config["model_version"]


def test_adapter_loads_postgresql_profiles_and_returns_model_payload_unchanged():
    with SessionLocal() as db:
        suffix = hashlib.sha1(str(date.today()).encode()).hexdigest()[:10]
        user_a = models.User(username=f"ml_a_{suffix}", email=f"ml_a_{suffix}@example.test", hashed_password="test")
        user_b = models.User(username=f"ml_b_{suffix}", email=f"ml_b_{suffix}@example.test", hashed_password="test")
        db.add_all([user_a, user_b])
        db.flush()
        db.add_all([
            models.UserProfile(user_id=user_a.id, date_of_birth=date(1990, 1, 1), gender="female", city="Pune", era="millennial", sexual_orientation_consent=True, is_face_verified=True, is_id_verified=True, verification_status="verified"),
            models.UserProfile(user_id=user_b.id, date_of_birth=date(1992, 1, 1), gender="male", city="Pune", era="millennial", sexual_orientation_consent=True, is_face_verified=True, is_id_verified=True, verification_status="verified"),
        ])
        db.commit()
        adapter = DatingMLAdapter()
        mapped = adapter.load_profile(db, user_a.id)
        assert db.get_bind().dialect.name == "postgresql"
        assert mapped["id"] == str(user_a.id)
        assert mapped["orientation"] is None
        result = adapter.predict_pair(db, user_a.id, user_b.id)
        assert result["eligible"] is False
        assert result["compatibility_score"] is None
        assert "model_version" in result
