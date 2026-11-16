"""One-shot entry point for an external daily verification-retention scheduler."""

import logging

from app.database import SessionLocal
from app.main import _run_verification_retention_maintenance


logger = logging.getLogger("bugzyme.verification_retention")


def main() -> int:
    try:
        with SessionLocal() as db:
            ran = _run_verification_retention_maintenance(db)
        if ran:
            logger.info("Verification retention maintenance completed")
        else:
            logger.info("Verification retention maintenance was already running")
        return 0
    except Exception:
        logger.exception("Verification retention maintenance failed; scheduler retry is required")
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    raise SystemExit(main())
