"""
Experimental Interest Comparison Service.

Provides an isolated, non-mutating demonstration calculation that compares
actual baseline Dating ML V3 ranking with a simulated interest-adjusted ranking.

Safety & Integrity Guarantees:
1. Zero mutation to core config.json or production ranking weights (production weight stays 0.00).
2. Zero mutation to SQLite database or persistent user profiles.
3. Completely separate endpoint and calculation path from production `/matches/rank` and `/matches/discover`.
4. Mandatory scientific disclaimers: Experimental scores are profile similarity metrics,
   NOT relationship-success probabilities.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from app.services.dating_ml_model.ranking import combine_signals
from app.services.dating_ml_model.interests import UserInterestProfile
from app.services.dating_ml_model.external_interests import generate_synthetic_google_data, MockGoogleInterestProvider
from app.services.ml_v3.model_adapter import dating_ml_v3_adapter, _map_profile

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENTAL_WEIGHT = 0.15


def run_experimental_comparison(
    user_profile: Dict[str, Any],
    candidate_profiles: List[Dict[str, Any]],
    experimental_weight: float = DEFAULT_EXPERIMENTAL_WEIGHT,
    synthetic_persona: str = "outdoors_tech",
    custom_interests: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Computes side-by-side baseline vs simulated experimental ranking.

    - Baseline uses production configuration where external_interest weight is strictly 0.00.
    - Experimental uses an isolated in-memory copy with experimental_weight applied to interests.
    - Neither calculation alters global configuration or database state.
    """
    if not (0.01 <= experimental_weight <= 0.50):
        raise ValueError("experimental_weight must be between 0.01 and 0.50")

    if not dating_ml_v3_adapter.is_available or dating_ml_v3_adapter._model is None:
        raise RuntimeError("Dating ML V3 engine is not available")

    # 1. Compute production baseline ranking (weight = 0.00)
    baseline_raw = dating_ml_v3_adapter.rank_candidates(
        user_profile, candidate_profiles, top_k=len(candidate_profiles)
    )

    # 2. Prepare synthetic demo interests for comparison if custom ones are not provided
    demo_interests = custom_interests
    if demo_interests is None:
        mock_prov = MockGoogleInterestProvider()
        synth_data = mock_prov.get_synthetic_data(synthetic_persona)
        extracted = mock_prov.extract_interests(user_profile.get("id", "me-001"), synth_data)
        demo_interests = [i.to_dict() for i in extracted.interests]

    # 3. Build interest profile for simulated comparison
    model_config = copy.deepcopy(dating_ml_v3_adapter._model.config)
    interest_profile = UserInterestProfile(model_config).fit(
        user_profile, [], lambda uid: None, None, external_interests=demo_interests
    )

    # 4. Compute simulated ranking with experimental weight
    experimental_config = copy.deepcopy(model_config)
    exp_weights = dict(experimental_config["final_ranking"]["weights"])
    exp_weights["interests"] = float(experimental_weight)
    experimental_config["final_ranking"]["weights"] = exp_weights

    # Map candidate profiles for fast lookup
    mapped_candidates = {str(c.get("id")): _map_profile(c) for c in candidate_profiles}
    user_mapped = _map_profile(user_profile)

    experimental_rows = []
    for base_rank_idx, base_item in enumerate(baseline_raw):
        cand_id = str(base_item.get("id") or base_item.get("user_b"))
        cand_mapped = mapped_candidates.get(cand_id)
        if not cand_mapped:
            continue

        # Score candidate interest alignment
        interest_res = interest_profile.score_candidate(cand_mapped)
        inter_score = interest_res.get("score")
        inter_conf = (interest_res.get("confidence") or 0.0) / 100.0
        aligned = interest_res.get("aligned_interests", [])

        # Build signals for experimental combine_signals
        signals = {
            "compatibility": {
                "score": base_item.get("compatibility_score"),
                "confidence": (base_item.get("confidence_score") or 100.0) / 100.0,
            }
        }
        if inter_score is not None and inter_conf > 0:
            signals["interests"] = {"score": inter_score, "confidence": inter_conf}

        exp_result = combine_signals(signals, experimental_config)
        exp_score = exp_result.get("final_score")
        if exp_score is None:
            # Fallback to adjusted score if signals cannot be combined
            exp_score = base_item.get("adjusted_score", 50.0)

        # Baseline adjusted score
        base_score = float(base_item.get("adjusted_score") or base_item.get("compatibility_score") or 50.0)

        clean_aligned = [
            t.replace("interest_tag:", "").replace("_", " ").title() for t in aligned
        ]

        experimental_rows.append({
            "candidate_id": cand_id,
            "name": cand_mapped.get("name", cand_id),
            "age": cand_mapped.get("age"),
            "location_city": cand_mapped.get("location_city"),
            "baseline_rank": base_rank_idx + 1,
            "baseline_score": round(base_score, 2),
            "simulated_score": round(float(exp_score), 2),
            "score_delta": round(float(exp_score) - base_score, 2),
            "shared_interests": clean_aligned,
            "interest_score": round(inter_score, 1) if inter_score is not None else None,
            "interest_confidence": round(inter_conf * 100, 1),
            "raw_base_item": base_item,
        })

    # Sort by simulated score descending to determine experimental rank
    experimental_rows.sort(key=lambda x: x["simulated_score"], reverse=True)

    comparison_results = []
    for exp_rank_idx, item in enumerate(experimental_rows):
        exp_rank = exp_rank_idx + 1
        base_rank = item["baseline_rank"]
        rank_delta = base_rank - exp_rank  # positive = improved rank

        comparison_results.append({
            "candidate_id": item["candidate_id"],
            "name": item["name"],
            "age": item["age"],
            "location_city": item["location_city"],
            "baseline_rank": base_rank,
            "experimental_rank": exp_rank,
            "rank_delta": rank_delta,
            "baseline_score": item["baseline_score"],
            "experimental_score": item["simulated_score"],
            "score_delta": item["score_delta"],
            "shared_interests": item["shared_interests"],
            "shared_interests_count": len(item["shared_interests"]),
            "explanation": (
                f"Simulated {item['score_delta']:+0.2f} pt adjustment based on "
                f"{len(item['shared_interests'])} shared hobby topic(s)."
                if item["shared_interests"]
                else "No shared hobby tags detected; score remained neutral."
            ),
        })

    return {
        "is_experimental": True,
        "demonstration_notice": "ISOLATED MODEL DEMONSTRATION — ZERO PRODUCTION IMPACT",
        "experimental_weight": float(experimental_weight),
        "synthetic_persona": synthetic_persona,
        "active_simulated_interests": [
            i.get("display_name") or i.get("canonical_token") for i in demo_interests[:5]
        ],
        "formula_disclosure": (
            f"Simulated Score = combine_signals(baseline_signals, weights={{'interests': {experimental_weight:.2f}}}). "
            "Confidence-scaled so sparse interests do not artificially swing scores."
        ),
        "scientific_disclaimer": (
            "EXPERIMENTAL DEMONSTRATION ONLY. These scores reflect simulated profile attribute alignment "
            "and shared hobby overlap. They are NOT scientific probabilities of relationship success, "
            "compatibility guarantees, or evidence of long-term partnership viability."
        ),
        "comparison": comparison_results,
    }

