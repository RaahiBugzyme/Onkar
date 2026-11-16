# Raahi Backend Environment Configuration Checklist

## Required Environment Variables (Mandatory - No Defaults)

| Variable | File(s) Used | Purpose | Default |
|---|---|---|---|
| **`DATABASE_URL`** | `app/database.py:10` | PostgreSQL connection string for all database operations | **None** - Mandatory; raises `RuntimeError` if missing |
| **`SECRET_KEY`** | `app/main.py:54` | JWT signing key for authentication tokens | **None** - Mandatory; raises `RuntimeError` if < 32 chars |

## Optional Environment Variables (With Defaults)

| Variable | File(s) Used | Default Value | Purpose |
|---|---|---|---|
| **`TOKEN_TTL_HOURS`** | `app/main.py:61` | `"24"` | Token time-to-live in hours for JWT access tokens |
| **`ALLOWED_ORIGINS`** | `app/main.py:63-67` | `"*"` (all origins) | CORS allowed origins, comma-separated list |
| **`ATTACHMENT_STORAGE_DIR`** | `app/storage.py:65` | `"storage/attachments"` | Base directory for attachment file storage |

## Feature-Specific Environment Variables

| Variable | File(s) Used | Purpose | Startup Required |
|---|---|---|---|
| **`GROQ_API_KEY`** | `app/ai/extraction.py:148` | API key for Groq LLM service | Not required for startup; only needed when AI features are used |

## Summary

### Mandatory for Startup
- `DATABASE_URL` - Required by `app/database.py`; application will fail to import without it
- `SECRET_KEY` - Required by `app/main.py`; JWT authentication will fail without it

### Optional (Defaults Provided)
- `TOKEN_TTL_HOURS` → `24` hours
- `ALLOWED_ORIGINS` → `"*"` (allow all)
- `ATTACHMENT_STORAGE_DIR` → `"storage/attachments"`

### Feature-Specific (Not Required for Startup)
- `GROQ_API_KEY` - Required only for Groq AI integrations (conversation coach, suggestion extraction)

### Files That Read Environment Variables
1. **`app/database.py`**: `DATABASE_URL`
2. **`app/main.py`**: `SECRET_KEY`, `TOKEN_TTL_HOURS`, `ALLOWED_ORIGINS`
3. **`app/storage.py`**: `ATTACHMENT_STORAGE_DIR`
4. **`app/ai/extraction.py`**: `GROQ_API_KEY`

### Startup Sequence
1. `from app.database import DATABASE_URL` → fails if not set
2. `from app.main import app` → `SECRET_KEY` validated (32+ chars)
3. FastAPI app initializes with CORS, middleware, and routes
4. Lifespan handler runs database schema checks and resets online status