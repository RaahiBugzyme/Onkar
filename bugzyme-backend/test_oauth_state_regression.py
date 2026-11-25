import hashlib
import json
import sqlite3
import time
import pytest
from app.services.google_auth import (
    generate_state,
    generate_pkce_pair,
    save_oauth_state,
    verify_and_consume_oauth_state,
    clear_oauth_states,
    _ACTIVE_STATES,
    _get_storage_db_path,
)

def setup_function():
    """Clear state store before each test."""
    clear_oauth_states()

def teardown_function():
    """Clean up state store after each test."""
    clear_oauth_states()

def test_valid_state_generation_and_consumption():
    """Valid state should be created and successfully consumed once."""
    state = generate_state()
    verifier, challenge = generate_pkce_pair()
    redirect_uri = "http://localhost:5173/auth/google/callback"

    assert state and isinstance(state, str)
    assert len(state) >= 32
    assert verifier and len(verifier) >= 43

    save_oauth_state(state, verifier, redirect_uri, user_id="user_123")

    # State can be verified and consumed
    consumed = verify_and_consume_oauth_state(state)
    assert consumed is not None
    assert consumed["code_verifier"] == verifier
    assert consumed["redirect_uri"] == redirect_uri
    assert consumed["user_id"] == "user_123"

def test_missing_or_empty_state():
    """Missing or empty state should return None without error."""
    assert verify_and_consume_oauth_state("") is None
    assert verify_and_consume_oauth_state(None) is None

def test_incorrect_or_tampered_state():
    """Unregistered or tampered state should return None."""
    state = generate_state()
    verifier, _ = generate_pkce_pair()
    save_oauth_state(state, verifier, "http://localhost:5173/auth/google/callback")

    tampered_state = state[:-2] + ("aa" if state[-2:] != "aa" else "bb")
    assert verify_and_consume_oauth_state(tampered_state) is None

def test_reused_state_rejected():
    """A consumed state cannot be used a second time (single-use invariant)."""
    state = generate_state()
    verifier, _ = generate_pkce_pair()
    save_oauth_state(state, verifier, "http://localhost:5173/auth/google/callback")

    first_attempt = verify_and_consume_oauth_state(state)
    assert first_attempt is not None
    assert first_attempt["code_verifier"] == verifier

    # Second consumption attempt with the same state must fail (single-use)
    second_attempt = verify_and_consume_oauth_state(state)
    assert second_attempt is None

def test_expired_state_rejected():
    """States older than 10 minutes (600s TTL) must be rejected."""
    state = generate_state()
    verifier, _ = generate_pkce_pair()
    save_oauth_state(state, verifier, "http://localhost:5173/auth/google/callback")

    # Artificially expire the state in SQLite & memory
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    past_timestamp = time.time() - 10  # 10 seconds in the past

    # Update in-memory if present
    if state in _ACTIVE_STATES:
        _ACTIVE_STATES[state]["expires_at"] = past_timestamp

    # Update sqlite
    db_path = _get_storage_db_path()
    assert db_path is not None and db_path.exists()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE oauth_states SET expires_at = ? WHERE state_hash = ?",
            (past_timestamp, state_hash),
        )
        conn.commit()

    # Attempt to consume expired state must fail
    assert verify_and_consume_oauth_state(state) is None

def test_backend_restart_and_process_resilience():
    """
    Simulates a Uvicorn worker reload or restart:
    State generated in one process lifecycle is stored in SQLite.
    When in-memory cache is wiped, the next request still recovers and consumes the state.
    """
    state = generate_state()
    verifier, _ = generate_pkce_pair()
    redirect_uri = "http://localhost:5173/auth/google/callback"
    save_oauth_state(state, verifier, redirect_uri)

    # Simulate worker restart by wiping the in-memory cache entirely
    _ACTIVE_STATES.clear()
    assert len(_ACTIVE_STATES) == 0

    # verify_and_consume_oauth_state should fall back to SQLite and succeed
    consumed = verify_and_consume_oauth_state(state)
    assert consumed is not None
    assert consumed["code_verifier"] == verifier
    assert consumed["redirect_uri"] == redirect_uri

    # Ensure it was deleted from SQLite as well (single-use preserved across restart)
    assert verify_and_consume_oauth_state(state) is None
