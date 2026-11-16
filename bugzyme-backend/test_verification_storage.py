"""Isolated tests for private identity evidence storage and upload validation."""

import pytest
from pathlib import Path
from cryptography.fernet import Fernet

from app import verification_storage


def configure_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(tmp_path))


def test_evidence_is_encrypted_private_and_deletable(monkeypatch, tmp_path):
    configure_storage(monkeypatch, tmp_path)
    evidence = b"\x89PNG\r\n\x1a\nprivate-test-evidence"

    evidence_key = verification_storage.save_evidence(evidence)
    stored = (tmp_path / evidence_key).read_bytes()

    assert stored != evidence
    assert verification_storage.read_evidence(evidence_key) == evidence
    assert verification_storage.delete_evidence(evidence_key) is True
    assert not (tmp_path / evidence_key).exists()


@pytest.mark.parametrize(
    ("content", "verification_type", "expected"),
    [
        (b"\x89PNG\r\n\x1a\nrest", "face", "image/png"),
        (b"%PDF-1.7 test", "id_govt", "application/pdf"),
    ],
)
def test_supported_signatures(content, verification_type, expected):
    assert verification_storage.identify_evidence(content, verification_type) == expected


def test_invalid_signature_rejected():
    with pytest.raises(ValueError):
        verification_storage.identify_evidence(b"not an image", "face")


def test_evidence_limit_enforced(monkeypatch, tmp_path):
    configure_storage(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        verification_storage.save_evidence(b"x" * (verification_storage.MAX_EVIDENCE_BYTES + 1))


def test_public_upload_directory_cannot_be_used(monkeypatch, tmp_path):
    monkeypatch.setenv("RAAHI_VERIFICATION_STORAGE_DIR", str(Path("uploads").resolve()))
    monkeypatch.setenv("RAAHI_VERIFICATION_FERNET_KEY", Fernet.generate_key().decode())
    with pytest.raises(verification_storage.EvidenceConfigurationError):
        verification_storage.require_workflow_configuration()


def test_evidence_key_path_traversal_rejected(monkeypatch, tmp_path):
    configure_storage(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        verification_storage.read_evidence("..\\private")
