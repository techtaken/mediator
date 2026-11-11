"""Maintenance jobs a scheduler (cron) calls.

Authenticated with X-Job-Token (the JOB_TOKEN setting) or a signed-in admin.
Each job is idempotent, so running it twice or late is harmless.
"""

import logging

from fastapi import APIRouter, Depends

from app.auth import job_or_admin
from app.config import get_settings
from app.followup_store import open_due_followups
from app.retention import purge_old_rooms, scrub_audit_reasons

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs")


@router.post("/retention")
def run_retention(caller: str = Depends(job_or_admin)):
    """Remove rooms older than RETENTION_DAYS and clear old audit reasoning."""
    settings = get_settings()
    result = {
        "rooms": purge_old_rooms(settings.retention_days),
        "audit": scrub_audit_reasons(settings.audit_reason_retention_days),
    }
    logger.info("retention job run by %s: %s", caller, result)
    return result


@router.post("/followups")
def run_followups(caller: str = Depends(job_or_admin)):
    """Open check-ins whose date has come. Run hourly."""
    opened = open_due_followups()
    logger.info("follow-up job run by %s: opened %d", caller, opened)
    return {"opened": opened}
