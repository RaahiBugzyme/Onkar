# Dating ML V3 Integration Architecture

This folder contains the isolated integration layer for HeartMatch's proprietary **Dating ML V3** model.

## Design Philosophy: Modular & Decoupled
1. **Interface Isolation**: The FastAPI web layer does not directly interact with model binaries or tensor shapes. It calls high-level domain methods on `dating_ml_v3_adapter` (`extract_features`, `predict_compatibility`, `rank_candidates`).
2. **Safe Fallback**: If the model binary is missing, updating, or running in dev mode without GPUs, the adapter falls back to calibrated heuristics, ensuring frontend and backend work reliably.
3. **Pluggable Weights**: When ready to connect the trained artifact:
   - Place your serialized model (e.g., `dating_ml_v3.pkl` or `.onnx`) in `backend/models/`.
   - Update `DATING_ML_V3_MODEL_PATH` in `backend/.env`.
   - The adapter handles feature vector transformation and batch inference automatically.
