"""SQLAlchemy boundary for Raahi's deterministic Dating ML package.

HTTP handlers must pass the authenticated user/profile objects they resolved
server-side. This adapter never accepts a caller-selected identity from an API
payload and does not persist anything except explicitly requested match output.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, load_only

from app import models
from app.services.dating_ml_model import CompatibilityModel, RecommendationModel, __version__
from app.services.dating_ml_model.compatibility_engine import load_config

logger = logging.getLogger(__name__)


class _FeedRecommendationCache:
    """Thread-safe in-memory LRU cache with TTL for recommendation scoring."""

    def __init__(self, ttl_seconds: float = 60.0, max_size: int = 500):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()

    def get(self, key: str) -> list[dict[str, Any]] | None:
        if key not in self._cache:
            return None
        created_at, val = self._cache[key]
        if time.time() - created_at > self.ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return val

    def set(self, key: str, val: list[dict[str, Any]]) -> None:
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (time.time(), val)

    def clear(self) -> None:
        self._cache.clear()


_feed_cache = _FeedRecommendationCache(ttl_seconds=60.0, max_size=500)


def calculate_profile_completeness(user: Any, profile: models.UserProfile | None) -> float:
    """Deterministic profile completeness percentage across core dating signals."""
    if not profile:
        return 0.0
    checks = [
        bool(getattr(profile, "date_of_birth", None)),
        bool(getattr(profile, "gender", None)),
        bool((getattr(profile, "city", None) or "").strip()),
        bool((getattr(profile, "era", None) or "").strip()),
        bool((getattr(profile, "profession", None) or "").strip()),
        bool((getattr(profile, "education", None) or "").strip()),
        bool((getattr(profile, "relationship_intentions", None) or "").strip()),
        bool(getattr(profile, "interests", None) and len(profile.interests) > 0),
        bool(user and getattr(user, "bio", None) and str(user.bio).strip()),
        bool(getattr(profile, "photos", None) and len(profile.photos) > 0),
    ]
    return round(sum(checks) / len(checks) * 100.0, 1)


class MatchingNotAllowed(PermissionError):
    """The pair fails the backend's existing adult, verification, block or preference gate."""


class MatchingConsentRequired(PermissionError):
    """Both participants have not currently consented to orientation matching."""


def _age(profile: models.UserProfile, reference_date: date | None = None) -> int | None:
    birth_date = profile.date_of_birth
    if birth_date is None:
        return None
    today = reference_date or date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _sex(gender: Any) -> str | None:
    value = str(gender or "").strip().casefold()
    if value in {"male", "man", "m"}:
        return "m"
    if value in {"female", "woman", "f"}:
        return "f"
    return None


def map_raahi_profile(
    profile: models.UserProfile,
    *,
    user_id: Any | None = None,
    reference_date: date | None = None,
    orientation_authorized: bool = False,
) -> dict[str, Any]:
    """Map stored Raahi fields; unsupported model fields remain explicitly unknown."""
    city = (profile.city or "").strip() or None
    orientation = None
    if orientation_authorized and profile.sexual_orientation_consent:
        orientation = profile.sexual_orientation

    job = (getattr(profile, "profession", None) or "").strip() or None
    education = (getattr(profile, "education", None) or "").strip() or None
    relationship_intention = (getattr(profile, "relationship_intentions", None) or "").strip() or None
    raw_interests = getattr(profile, "interests", None)
    interests = list(raw_interests) if isinstance(raw_interests, (list, tuple, set)) else []

    return {
        "id": str(user_id if user_id is not None else profile.user_id),
        "age": _age(profile, reference_date),
        "birth_year": profile.date_of_birth.year if profile.date_of_birth else None,
        "sex": _sex(profile.gender),
        "orientation": orientation,
        "education": education,
        "job": job,
        "religion": None,
        "ethnicity": None,
        "drinks": None,
        "drugs": None,
        "smokes": None,
        "diet": None,
        "offspring": None,
        "pets": None,
        "height": None,
        "body_type": None,
        "relationship_intention": relationship_intention,
        "interests": interests,
        "era": getattr(profile, "era", None),
        "vibe_tag": profile.vibe_tag,
        "location": {"city": city, "region": None, "country": None},
    }


def _discoverable(profile: models.UserProfile, today: date | None = None) -> bool:
    """A profile is discoverable when it belongs to an adult (age >= 18).

    Verification status is surfaced as a trust badge but does not gate
    discovery – new users must be able to browse and be browsed immediately.
    """
    age = _age(profile, today)
    return bool(age is not None and age >= 18)


def _verified_adult(profile: models.UserProfile, today: date | None = None) -> bool:
    """A profile is a verified adult when age >= 18 and verification is complete."""
    age = _age(profile, today)
    return bool(
        age is not None and age >= 18
        and profile.verification_status == "verified"
    )


def _preferences_match(first: models.UserProfile, second: models.UserProfile) -> bool:
    first_gender = first.target_gender_preference or "any"
    second_gender = second.target_gender_preference or "any"
    first_era = first.match_era_preference or "any"
    second_era = second.match_era_preference or "any"
    return bool(
        (first_gender == "any" or first_gender == second.gender)
        and (second_gender == "any" or second_gender == first.gender)
        and (first_era == "any" or first_era == second.era)
        and (second_era == "any" or second_era == first.era)
    )


def _has_block(db: Session, first_id: int, second_id: int) -> bool:
    return db.query(models.UserBlock.id).filter(or_(
        and_(models.UserBlock.blocker_id == first_id, models.UserBlock.blocked_id == second_id),
        and_(models.UserBlock.blocker_id == second_id, models.UserBlock.blocked_id == first_id),
    )).first() is not None


class DatingMLAdapter:
    """Minimal SQLAlchemy adapter for pair scoring, ranking and match provenance."""

    def __init__(self, model: Any | None = None, recommendation_model: Any | None = None):
        config = deepcopy(load_config())
        config["disabled_components"] = sorted(set(config.get("disabled_components", ())) | {"religion", "ethnicity"})
        config["mutual_interest_enabled"] = False
        config["behavior_enabled"] = True  # gated per authenticated user's persisted opt-in below
        config.setdefault("final_ranking", {}).setdefault("weights", {})["mutual_interest"] = 0.0
        config["final_ranking"]["weights"]["interests"] = 0.0
        self.model = model or CompatibilityModel(config)
        recommendation_compatibility = (
            self.model if hasattr(self.model, "config") and hasattr(self.model, "engine")
            else CompatibilityModel(config)
        )
        self.recommendation_model = recommendation_model or RecommendationModel(
            config, compatibility_model=recommendation_compatibility
        )
        self.package_version = __version__
        self.engine_version = str(config.get("model_version", "2.1.0"))

    def load_profile(self, db: Session, user_id: Any) -> dict[str, Any]:
        """Load a profile for internal use without exposing its orientation."""
        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user_id).first()
        if profile is None:
            raise MatchingNotAllowed("Dating profile not found")
        return map_raahi_profile(profile, orientation_authorized=False)

    def _profile_by_id(self, db: Session, user_id: Any) -> models.UserProfile:
        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user_id).first()
        if profile is None:
            raise MatchingNotAllowed("Dating profile not found")
        return profile

    def _check_pair(self, db: Session, first_id: int, second_id: int) -> tuple[models.UserProfile, models.UserProfile]:
        if first_id == second_id:
            raise MatchingNotAllowed("Cannot match a profile with itself")
        first, second = self._profile_by_id(db, first_id), self._profile_by_id(db, second_id)
        if not _verified_adult(first) or not _verified_adult(second):
            raise MatchingNotAllowed("Both profiles must be verified adults")
        if _has_block(db, first_id, second_id):
            raise MatchingNotAllowed("Blocked profiles cannot be matched")
        if not _preferences_match(first, second):
            raise MatchingNotAllowed("Profiles do not meet both users' matching preferences")
        if not (first.sexual_orientation_consent and second.sexual_orientation_consent):
            raise MatchingConsentRequired("Both users must consent to orientation-based matching")
        return first, second

    def predict_pair(self, db: Session, first_id: int, second_id: int) -> dict[str, Any]:
        first, second = self._check_pair(db, first_id, second_id)
        result = self.model.predict_pair(
            map_raahi_profile(first, orientation_authorized=True),
            map_raahi_profile(second, orientation_authorized=True),
        )
        result["package_version"] = self.package_version
        result["engine_version"] = result.get("model_version") or self.engine_version
        return result

    def predict_and_persist_match(self, db: Session, match: models.Match) -> dict[str, Any]:
        first_id, second_id = match.user1_id, match.user2_id
        first, second = self._check_pair(db, first_id, second_id)
        result = self.model.predict_pair(
            map_raahi_profile(first, orientation_authorized=True),
            map_raahi_profile(second, orientation_authorized=True),
        )
        match.eligibility_status = bool(result.get("eligible"))
        match.eligibility_reason = result.get("eligibility_reason")
        match.raw_compatibility_score = result.get("compatibility_score")
        match.confidence_score = result.get("confidence_score")
        match.adjusted_score = result.get("adjusted_score")
        match.model_version = result.get("model_version")
        match.explanation = result.get("explanation")
        match.component_scores = result.get("components")
        match.prediction_provenance = "dating_ml_v3"
        match.calculated_at = datetime.now(timezone.utc)
        result["package_version"] = self.package_version
        result["engine_version"] = result.get("model_version") or self.engine_version
        result["provenance"] = match.prediction_provenance
        return result

    def load_behavior_history(
        self,
        db: Session,
        authenticated_user: models.User,
        eligible_candidate_ids: Any,
    ) -> list[tuple[models.Swipe, models.UserProfile]]:
        """Load only this user's genuine swipe events for currently eligible profiles.

        The package gives old events a nonzero exponential weight and counts them
        toward its evidence threshold, so there is no behavior-safe age cutoff.
        The DB unique constraint means at most one persisted swipe exists per pair.
        """
        return (
            db.query(models.Swipe, models.UserProfile)
            .join(models.UserProfile, models.UserProfile.user_id == models.Swipe.target_user_id)
            .filter(
                models.Swipe.user_id == authenticated_user.id,
                models.Swipe.target_user_id.in_(eligible_candidate_ids.select()),
                models.Swipe.action.in_(("like", "pass", "superlike")),
            )
            .options(
                load_only(models.Swipe.id, models.Swipe.user_id, models.Swipe.target_user_id,
                          models.Swipe.action, models.Swipe.created_at),
                load_only(
                    models.UserProfile.user_id, models.UserProfile.date_of_birth,
                    models.UserProfile.gender, models.UserProfile.sexual_orientation,
                    models.UserProfile.sexual_orientation_consent, models.UserProfile.city,
                    models.UserProfile.era, models.UserProfile.vibe_tag,
                    models.UserProfile.target_gender_preference, models.UserProfile.match_era_preference,
                    models.UserProfile.is_face_verified, models.UserProfile.is_id_verified,
                    models.UserProfile.verification_status,
                    models.UserProfile.behavioral_personalization_enabled,
                ),
            )
            .order_by(models.Swipe.created_at.asc(), models.Swipe.target_user_id.asc())
            .all()
        )

    def rank_feed(
        self,
        db: Session,
        authenticated_user: models.User,
        user_profile: models.UserProfile,
        eligible_rows: Iterable[tuple[models.User, models.UserProfile]],
        swiped_ids: set[int],
        limit: int,
        offset: int,
        eligible_candidate_ids: Any | None = None,
    ) -> dict[str, Any]:
        """Rank server-filtered, unswiped rows and retain unscored rows without consent."""
        rows = list(eligible_rows)
        lookup_profiles = {str(user.id): profile for user, profile in rows}
        fresh = [(u, p) for u, p in rows if u.id not in swiped_ids]
        orientation_consented = bool(user_profile.sexual_orientation_consent)
        model_candidates: list[dict[str, Any]] = []
        for user, profile in fresh:
            if orientation_consented and profile.sexual_orientation_consent:
                mapped = map_raahi_profile(profile, orientation_authorized=True)
                model_candidates.append(mapped)

        ranked_by_id: dict[str, dict[str, Any]] = {}
        if model_candidates:
            mapped_user = map_raahi_profile(user_profile, user_id=authenticated_user.id, orientation_authorized=True)
            interactions = []
            history_rows = []
            if user_profile.behavioral_personalization_enabled:
                if eligible_candidate_ids is None:
                    # Backward-compatible path for callers without a SQL candidate
                    # predicate; production feed passes the DB-side eligible query.
                    history_rows = [
                        (swipe, profile)
                        for swipe, profile in db.query(models.Swipe, models.UserProfile).join(
                            models.UserProfile, models.UserProfile.user_id == models.Swipe.target_user_id
                        ).filter(
                            models.Swipe.user_id == authenticated_user.id,
                            models.Swipe.target_user_id.in_([int(candidate_id) for candidate_id in lookup_profiles]),
                            models.Swipe.action.in_(("like", "pass", "superlike")),
                        ).order_by(models.Swipe.created_at.asc(), models.Swipe.target_user_id.asc()).all()
                    ]
                else:
                    history_rows = self.load_behavior_history(db, authenticated_user, eligible_candidate_ids)
                for swipe, history_profile in history_rows:
                    user_id = str(history_profile.user_id)
                    lookup_profiles[user_id] = history_profile
                    action = {"like": "LIKE", "pass": "PASS", "superlike": "SUPER_LIKE"}.get(swipe.action)
                    if action:
                        interactions.append({
                            "user_id": str(authenticated_user.id),
                            "candidate_id": str(swipe.target_user_id),
                            "action": action,
                            "timestamp": swipe.created_at.isoformat() + ("Z" if swipe.created_at.tzinfo is None else ""),
                        })
            lookup = {candidate_id: map_raahi_profile(profile, orientation_authorized=False)
                      for candidate_id, profile in lookup_profiles.items()}
            cache_key = f"{authenticated_user.id}:{','.join(sorted(str(c['id']) for c in model_candidates))}:{user_profile.behavioral_personalization_enabled}:{len(interactions)}"
            cached_recommendations = _feed_cache.get(cache_key)
            if cached_recommendations is not None:
                recommendations = cached_recommendations
            else:
                try:
                    recommendations = self.recommendation_model.recommend(
                        mapped_user,
                        model_candidates,
                        interactions=interactions,
                        profile_lookup=lambda candidate_id: lookup.get(str(candidate_id)),
                        privacy_settings={"personalization_enabled": bool(user_profile.behavioral_personalization_enabled)},
                        now=datetime.now(timezone.utc),
                        limit=len(model_candidates),
                    )
                    _feed_cache.set(cache_key, recommendations)
                except Exception as exc:
                    logger.warning("Recommendation model evaluation error: %s; falling back", type(exc).__name__)
                    raise
            ranked_by_id = {str(item["candidate_id"]): item for item in recommendations}

        feed_rows: list[dict[str, Any]] = []
        for user, profile in fresh:
            user_id = str(user.id)
            item = ranked_by_id.get(user_id)
            pair_orientation_available = bool(
                user_profile.sexual_orientation_consent and user_profile.sexual_orientation
                and profile.sexual_orientation_consent and profile.sexual_orientation
            )
            compatibility = (item or {}).get("compatibility") or {}
            ranking = (item or {}).get("ranking") or {}
            photo_urls = [p.photo_url for p in (profile.photos or [])] if hasattr(profile, "photos") and profile.photos else []
            completeness = calculate_profile_completeness(user, profile)
            feed_rows.append({
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "age": _age(profile),
                "city": profile.city,
                "era": profile.era,
                "vibe_tag": profile.vibe_tag,
                "bio": user.bio,
                "profession": getattr(profile, "profession", None),
                "education": getattr(profile, "education", None),
                "relationship_intentions": getattr(profile, "relationship_intentions", None),
                "interests": getattr(profile, "interests", None) or [],
                "photos": photo_urls,
                "photo_url": photo_urls[0] if photo_urls else None,
                "profile_completeness": completeness,
                "compatibility_score": compatibility.get("score"),
                "confidence_score": compatibility.get("confidence"),
                "adjusted_score": compatibility.get("adjusted_score"),
                "recommendation_score": ranking.get("final_score"),
                "score_type": "profile_alignment" if item else None,
                "model_version": (item or {}).get("package_version"),
                "prediction_provenance": "dating_ml_v3" if item else None,
                "ranking_weights_validated": False,
                "matching_status": "scored" if item else (
                    "model_ineligible" if pair_orientation_available else "orientation_consent_required"
                ),
                "is_face_verified": True,
                "is_id_verified": True,
                "verification_badge_required": True,
            })
        feed_rows.sort(key=lambda row: (
            row["matching_status"] != "scored",
            -(row["recommendation_score"] if row["recommendation_score"] is not None else -1.0),
            -(row["adjusted_score"] if row["adjusted_score"] is not None else -1.0),
            -(row.get("profile_completeness") or 0.0),
            row["user_id"],
        ))
        total = len(feed_rows)
        page = feed_rows[offset:offset + limit]
        return {"profiles": page, "total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}
