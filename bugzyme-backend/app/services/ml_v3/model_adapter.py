"""
Adapter for the Dating ML V2.2 compatibility engine.

This module is the single integration point between the HeartMatch backend API
and the `dating_ml_model` package.  All scoring is delegated to the package's
public API.  This file does NOT re-implement any scoring formulas.

Field mapping (HeartMatch app schema → OkCupid schema expected by dating_ml_model):
  id / user_id       → id
  age                → age              (integer, years)
  sex / gender       → sex              ("m" | "f")
  orientation        → orientation      ("straight" | "gay" | "bisexual")
  education          → education        (string, optional)
  job / profession   → job              (string, optional)
  religion           → religion         (string, optional)
  ethnicity          → ethnicity        (string, optional – comma-separated)
  drinks             → drinks           (string, optional)
  drugs              → drugs            (string, optional)
  smokes             → smokes           (string, optional)
  diet               → diet             (string, optional)
  offspring          → offspring        (string, optional)
  pets               → pets             (string, optional)
  height_cm          → height           (float, converted cm→inches, optional)
  height_in / height → height           (float, inches, optional, takes priority)
  body_type          → body_type        (string, optional)
  latitude + longitude → location.lat/lon (optional)
  location_city      → location.city    (optional)
  location_region    → location.region  (optional)
  location_country   → location.country (optional)

Missing optional fields are passed as None (the engine treats unknown as no-penalty,
not as a mismatch – see README §Scoring and adjusted_score shrinkage formula).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── engine import (lazy-safe) ──────────────────────────────────────────────────


def _try_import():
    """Return (CompatibilityModel, RecommendationService, HeartMatchRecommendationRepository, version_str) or (None, None, None, error_msg)."""
    try:
        from app.services.dating_ml_model import CompatibilityModel, RecommendationModel
        from app.services.dating_ml_model import __version__ as _ver
        from app.services.dating_ml_model.repository import RecommendationRepository
        from app.services.dating_ml_model.service import RecommendationService
        from app.db.sqlite_repository import default_sqlite_repo

        class HeartMatchRecommendationRepository(RecommendationRepository):
            """
            HeartMatch persistent SQL recommendation repository.
            Uses SQLite to persist profiles, preferences, interests, and privacy settings,
            surviving backend restarts. Auto-seeds standard demo profiles idempotently.
            """

            def __init__(self, sqlite_repo=None):
                self.sqlite_repo = sqlite_repo or default_sqlite_repo
                self.sqlite_repo.seed_demo_data_if_needed()
                self._interactions = []
                self._personalities = {}

            def get(self, user_id: Any) -> Optional[Dict[str, Any]]:
                uid = str(user_id)
                prof = self.sqlite_repo.get_profile(uid)
                if prof is None:
                    prof = {"id": uid}
                    self.sqlite_repo.save_profile(prof)
                return dict(prof)

            def all(self) -> List[Dict[str, Any]]:
                return self.sqlite_repo.get_all_profiles()

            def get_candidate_profiles(self, exclude_user_id: Any = None) -> List[Dict[str, Any]]:
                return self.sqlite_repo.get_candidate_profiles(exclude_user_id=exclude_user_id)

            def save_profile(self, profile: Dict[str, Any], is_demo: bool = False) -> Dict[str, Any]:
                return self.sqlite_repo.save_profile(profile, is_demo=is_demo)

            def delete_profile(self, user_id: Any) -> bool:
                return self.sqlite_repo.delete_profile(user_id)

            def get_user_preferences(self, user_id: Any) -> Optional[Dict[str, Any]]:
                return self.sqlite_repo.get_user_preferences(user_id)

            def save_user_preferences(self, user_id: Any, preferences: Dict[str, Any]) -> Dict[str, Any]:
                return self.sqlite_repo.save_user_preferences(user_id, preferences)

            def get_privacy_settings(self, user_id: Any) -> Dict[str, Any]:
                return self.sqlite_repo.get_privacy_settings(user_id)

            def save_privacy_settings(self, user_id: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
                return self.sqlite_repo.save_privacy_settings(user_id, settings)

            def get_external_interests(self, user_id: Any, provider: Optional[str] = None) -> List[Dict[str, Any]]:
                return self.sqlite_repo.get_external_interests(user_id, provider=provider)

            def save_external_interests(self, user_id: Any, provider: str, interests: List[Dict[str, Any]]) -> Dict[str, Any]:
                return self.sqlite_repo.save_external_interests(user_id, provider, interests)

            def delete_external_interests(self, user_id: Any, provider: Optional[str] = None) -> int:
                return self.sqlite_repo.delete_external_interests(user_id, provider=provider)

            def remove_external_interest(self, user_id: Any, token: str, provider: Optional[str] = None) -> int:
                return self.sqlite_repo.remove_external_interest(user_id, token, provider=provider)

            def update_external_interest(self, user_id: Any, token: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                return self.sqlite_repo.update_external_interest(user_id, token, updates)

            def get_external_accounts(self, user_id: Any) -> List[Dict[str, Any]]:
                exts = self.sqlite_repo.get_external_interests(user_id)
                by_prov = {}
                for i in exts:
                    p = str(i.get("provider", "")).lower()
                    if p not in by_prov:
                        by_prov[p] = {"provider": p, "user_id": str(user_id), "item_count": 0, "updated_at": i.get("imported_at")}
                    by_prov[p]["item_count"] += 1
                return list(by_prov.values())

            def get_interactions(self, user_id: Any) -> List[Dict[str, Any]]:
                return [dict(e) for e in self._interactions if str(e.get("user_id")) == str(user_id)]

            def save_interaction(self, event: Dict[str, Any]) -> Dict[str, Any]:
                self._interactions.append(dict(event))
                return dict(event)

            def delete_interactions(self, user_id: Any) -> int:
                before = len(self._interactions)
                self._interactions = [e for e in self._interactions if str(e.get("user_id")) != str(user_id)]
                return before - len(self._interactions)

            def get_blocked_user_ids(self, user_id: Any) -> List[str]:
                return []

            def block_user(self, user_id: Any, blocked_user_id: Any) -> Dict[str, Any]:
                return {"user_id": str(user_id), "blocked_user_id": str(blocked_user_id), "blocked": True}

            def unblock_user(self, user_id: Any, blocked_user_id: Any) -> Dict[str, Any]:
                return {"user_id": str(user_id), "blocked_user_id": str(blocked_user_id), "blocked": False}

        return CompatibilityModel, RecommendationService, HeartMatchRecommendationRepository, str(_ver)
    except Exception as exc:  # noqa: BLE001
        return None, None, None, str(exc)


_CompatibilityModel, _RecommendationService, _HeartMatchRepo, _IMPORT_STATUS = _try_import()
_ENGINE_AVAILABLE: bool = _CompatibilityModel is not None

if _ENGINE_AVAILABLE:
    logger.info("dating_ml_model v%s imported successfully.", _IMPORT_STATUS)
else:
    logger.warning("dating_ml_model import failed: %s", _IMPORT_STATUS)


# ── field mapping helpers ──────────────────────────────────────────────────────

_CM_TO_IN = 1 / 2.54


def _map_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a HeartMatch profile dict to the OkCupid field schema expected by
    the compatibility engine.  Only fields present in the input are forwarded;
    absent optional fields are omitted (the engine treats them as unknown).
    """
    out: Dict[str, Any] = {}

    # Required – identity
    _copy_first(out, profile, "id", ("id", "user_id"))

    # Required – eligibility
    _copy_first(out, profile, "age", ("age",))
    _copy_first(out, profile, "sex", ("sex", "gender"))
    _copy_first(out, profile, "orientation", ("orientation", "sexual_orientation"))

    # Optional – career & education
    _copy_first(out, profile, "education", ("education", "education_level"))
    _copy_first(out, profile, "job", ("job", "profession", "occupation"))

    # Optional – values & culture
    _copy_first(out, profile, "religion", ("religion",))
    _copy_first(out, profile, "ethnicity", ("ethnicity",))

    # Optional – lifestyle
    _copy_first(out, profile, "drinks", ("drinks", "drinking"))
    _copy_first(out, profile, "drugs", ("drugs",))
    _copy_first(out, profile, "smokes", ("smokes", "smoking"))
    _copy_first(out, profile, "diet", ("diet", "dietary_preference"))

    # Optional – family
    _copy_first(out, profile, "offspring", ("offspring", "children_stance", "wants_children"))
    _copy_first(out, profile, "pets", ("pets",))

    # Optional – attraction / physical
    # height_in / height take priority over height_cm
    if "height_in" in profile and profile["height_in"] is not None:
        out["height"] = float(profile["height_in"])
    elif "height" in profile and profile["height"] is not None:
        out["height"] = float(profile["height"])
    elif "height_cm" in profile and profile["height_cm"] is not None:
        out["height"] = round(float(profile["height_cm"]) * _CM_TO_IN, 2)

    _copy_first(out, profile, "body_type", ("body_type",))

    # Optional – relationship intent (v2.2 signal)
    _copy_first(out, profile, "relationship_intention",
                ("relationship_intention", "relationship_goal", "looking_for"))

    # Optional – location (v2.2 layer)
    location: Dict[str, Any] = {}
    if profile.get("latitude") is not None and profile.get("longitude") is not None:
        location["lat"] = float(profile["latitude"])
        location["lon"] = float(profile["longitude"])
    _copy_first(location, profile, "city", ("location_city", "city"))
    _copy_first(location, profile, "region", ("location_region", "region", "state"))
    _copy_first(location, profile, "country", ("location_country", "country"))
    if location:
        out["location"] = location

    return out


def _copy_first(target: Dict, source: Dict, target_key: str,
                source_keys: tuple) -> None:
    """Copy the first found non-None value from source_keys into target."""
    for k in source_keys:
        if k in source and source[k] is not None:
            target[target_key] = source[k]
            return


# ── public adapter API ─────────────────────────────────────────────────────────

class DatingMLV3Adapter:
    """
    Thin delegation wrapper around the dating_ml_model CompatibilityModel.

    Replaces the previous hand-rolled heuristic adapter.  All scoring
    is performed by the engine; this class only handles field mapping,
    singleton lifecycle, and graceful unavailability reporting.
    """

    def __init__(self):
        self.is_available: bool = _ENGINE_AVAILABLE
        self.engine_version: str = _IMPORT_STATUS if _ENGINE_AVAILABLE else "unavailable"
        self._model = None
        self._repository = None
        self._recommendation_service = None

        if self.is_available:
            try:
                self._model = _CompatibilityModel()
                self._repository = _HeartMatchRepo()
                self._recommendation_service = _RecommendationService(self._model, self._repository)
                logger.info("CompatibilityModel and RecommendationService instantiated (engine v%s).", self.engine_version)
            except Exception as exc:  # noqa: BLE001
                self.is_available = False
                self.engine_version = f"instantiation error: {exc}"
                logger.error("CompatibilityModel could not be instantiated: %s", exc)

    # ── pair scoring ──────────────────────────────────────────────────────────

    def predict_pair(
        self,
        profile_a: Dict[str, Any],
        profile_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score two profiles against each other.

        Returns the full engine result dict (eligibility, compatibility_score,
        confidence_score, adjusted_score, categories, components, explanation,
        model_version).  If the engine is unavailable, returns an explicit error
        dict rather than a fabricated score.
        """
        if not self.is_available or self._model is None:
            return {
                "eligible": False,
                "eligibility_reason": "Compatibility engine not available",
                "compatibility_score": None,
                "confidence_score": None,
                "adjusted_score": None,
                "engine_status": self.engine_version,
            }
        mapped_a = _map_profile(profile_a)
        mapped_b = _map_profile(profile_b)
        result = self._model.predict_pair(mapped_a, mapped_b)
        result["engine_version"] = self.engine_version
        return result

    # ── eligibility check ─────────────────────────────────────────────────────

    def check_eligibility(
        self,
        profile_a: Dict[str, Any],
        profile_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return the eligibility gate result without running full scoring."""
        if not self.is_available or self._model is None:
            return {"eligible": False, "reason": "Compatibility engine not available"}
        return self._model.check_eligibility(_map_profile(profile_a), _map_profile(profile_b))

    # ── batch ranking ─────────────────────────────────────────────────────────

    def rank_candidates(
        self,
        user_profile: Dict[str, Any],
        candidate_profiles: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Score and rank a list of candidate profiles against a user profile.

        Returns a list of full engine result dicts sorted by adjusted_score
        (descending), filtered to eligible pairs only, limited to top_k.
        Ineligible candidates are excluded, not penalised with a zero score.
        """
        if not self.is_available or self._model is None:
            return []
        mapped_user = _map_profile(user_profile)
        mapped_candidates = [_map_profile(c) for c in candidate_profiles]
        results = self._model.predict_matches(mapped_user, mapped_candidates, top_k=top_k)
        for r in results:
            r["engine_version"] = self.engine_version
        return results

    # ── manual interests ──────────────────────────────────────────────────────

    def add_manual_interest(
        self,
        user_id: Any,
        name: str,
        category: Optional[str] = None,
        user_confirmed: bool = True,
    ) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.add_manual_interest(
            user_id, name, category=category, user_confirmed=user_confirmed
        )

    def add_manual_interests(
        self,
        user_id: Any,
        interests: List[Any],
    ) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.add_manual_interests(user_id, interests)

    def get_manual_interests(self, user_id: Any) -> List[Dict[str, Any]]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.get_manual_interests(user_id)

    def remove_manual_interest(self, user_id: Any, token_or_name: str) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.remove_manual_interest(user_id, token_or_name)

    def delete_manual_interests(self, user_id: Any) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.delete_manual_interests(user_id)

    def confirm_interest(
        self,
        user_id: Any,
        token_or_name: str,
        confirmed: bool = True,
    ) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.confirm_interest(user_id, token_or_name, confirmed=confirmed)

    def set_manual_interest_consent(self, user_id: Any, consent: bool) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.set_manual_interest_consent(user_id, consent)

    # ── external interests (Phase 1 mock providers) ───────────────────────────

    def list_external_providers(self) -> List[Dict[str, Any]]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        providers = []
        for p_id, p_inst in self._recommendation_service.mock_providers.items():
            providers.append({
                "id": p_inst.provider_id,
                "display_name": p_inst.display_name,
                "description": p_inst.description,
                "is_mock": p_inst.is_mock,
                "is_available": p_inst.is_available,
                "supported_scopes": p_inst.supported_scopes,
                "supported_personas": p_inst.supported_personas,
            })
        return providers

    def preview_external_interests(
        self,
        user_id: Any,
        provider: str,
        payload: Optional[Dict[str, Any]] = None,
        persona: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        p_name = str(provider).lower()
        prov = self._recommendation_service.mock_providers.get(p_name)
        if prov is None:
            raise ValueError(f"unsupported external provider '{provider}'; available: {list(self._recommendation_service.mock_providers.keys())}")
        preview_payload = prov.preview_interests(user_id, payload=payload, persona=persona)
        consent_active = self._recommendation_service.privacy_manager.get_external_interest_consent(user_id, p_name)
        return {
            **preview_payload.to_dict(),
            "is_mock": True,
            "consent_active": consent_active,
        }

    def import_external_interests(
        self,
        user_id: Any,
        provider: str,
        payload: Optional[Dict[str, Any]] = None,
        persona: Optional[str] = None,
        user_confirmed: bool = False,
        selected_tokens: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        p_name = str(provider).lower()
        prov = self._recommendation_service.mock_providers.get(p_name)
        if prov is None:
            raise ValueError(f"unsupported external provider '{provider}'; available: {list(self._recommendation_service.mock_providers.keys())}")

        # Enforce explicit consent before import
        consent = self._recommendation_service.privacy_manager.get_external_interest_consent(user_id, p_name)
        if not consent:
            raise PermissionError(
                f"Explicit consent is required before importing external interests from '{provider}'. Please enable consent first."
            )

        data = payload if payload is not None else prov.get_synthetic_data(persona)
        extracted = prov.extract_interests(user_id, data)

        from dataclasses import replace
        filtered_interests = extracted.interests
        if selected_tokens is not None:
            tok_set = set(selected_tokens)
            filtered_interests = [i for i in filtered_interests if i.canonical_token in tok_set]

        if user_confirmed:
            filtered_interests = [replace(i, user_confirmed=True) for i in filtered_interests]

        items_dict = [i.to_dict() for i in filtered_interests]
        saved = self._recommendation_service.repository.save_external_interests(user_id, p_name, items_dict)

        return {
            "user_id": str(user_id),
            "provider": p_name,
            "imported_count": len(items_dict),
            "interests": items_dict,
            "warnings": extracted.warnings,
            "total_stored": saved.get("total_external_interests", len(items_dict)),
            "is_mock": True,
        }

    def get_external_interests(self, user_id: Any, provider: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.get_external_interests(user_id, provider=provider)

    def delete_external_interests(self, user_id: Any, provider: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.delete_external_interests(user_id, provider=provider)

    def set_external_interest_consent(self, user_id: Any, provider: str, consent: bool) -> Dict[str, Any]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._recommendation_service.set_external_interest_consent(user_id, provider, consent)

    def get_external_interest_consent(self, user_id: Any, provider: str) -> bool:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        self._recommendation_service._user(user_id)
        privacy = self._recommendation_service.repository.get_privacy_settings(user_id)
        self._recommendation_service.privacy_manager.update_settings(user_id, privacy)
        return self._recommendation_service.privacy_manager.get_external_interest_consent(user_id, provider)

    def get_all_external_consent(self, user_id: Any) -> Dict[str, bool]:
        if not self.is_available or self._recommendation_service is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        self._recommendation_service._user(user_id)
        privacy = self._recommendation_service.repository.get_privacy_settings(user_id)
        self._recommendation_service.privacy_manager.update_settings(user_id, privacy)
        return {
            p: self._recommendation_service.privacy_manager.get_external_interest_consent(user_id, p)
            for p in ("google", "instagram", "manual_entry")
        }

    # ── profile persistence (Phase 3) ─────────────────────────────────────────

    def get_profile(self, user_id: Any) -> Optional[Dict[str, Any]]:
        if not self.is_available or self._repository is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._repository.get(user_id)

    def save_profile(self, profile: Dict[str, Any], is_demo: bool = False) -> Dict[str, Any]:
        if not self.is_available or self._repository is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._repository.save_profile(profile, is_demo=is_demo)

    def get_candidate_profiles(self, exclude_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.is_available or self._repository is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._repository.get_candidate_profiles(exclude_user_id=exclude_user_id)

    def delete_profile(self, user_id: Any) -> bool:
        if not self.is_available or self._repository is None:
            raise RuntimeError(f"Compatibility engine not available: {self.engine_version}")
        return self._repository.delete_profile(user_id)

    def seed_demo_profiles(self) -> None:
        if self._repository and hasattr(self._repository, "sqlite_repo"):
            self._repository.sqlite_repo.seed_demo_data_if_needed()

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a status dict suitable for the health endpoint."""
        return {
            "engine_available": self.is_available,
            "engine_version": self.engine_version,
            "trained_model_artifact": False,   # no .pkl / .joblib shipped
            "algorithm": "deterministic profile-alignment (unsupervised)",
        }


# ── singleton ─────────────────────────────────────────────────────────────────
dating_ml_v3_adapter = DatingMLV3Adapter()
