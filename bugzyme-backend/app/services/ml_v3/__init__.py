"""
ML V3 service module — delegates to the dating_ml_model package.
"""
from app.services.ml_v3.model_adapter import DatingMLV3Adapter, dating_ml_v3_adapter

__all__ = ["DatingMLV3Adapter", "dating_ml_v3_adapter"]
