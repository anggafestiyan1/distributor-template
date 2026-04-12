"""Core services — including the activity log helper."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_activity(
    user,
    action: str,
    description: str,
    target=None,
    details: dict | None = None,
    request=None,
) -> None:
    """Create an ActivityLog entry.

    Args:
        user: User instance (or None for system actions)
        action: One of ActivityLog.ACTION_* constants
        description: Short human-readable description (max 500 chars)
        target: Optional model instance (extracts target_type + target_id)
        details: Optional dict for extra context
        request: Optional HttpRequest for IP extraction

    Never raises — logs internally if it fails so caller is not affected.
    """
    from apps.core.models import ActivityLog

    try:
        target_type = ""
        target_id = ""
        if target is not None:
            target_type = target.__class__.__name__
            target_id = str(getattr(target, "pk", "") or "")

        ip = None
        if request is not None:
            ip = _get_client_ip(request)

        ActivityLog.objects.create(
            user=user if (user and getattr(user, "is_authenticated", False)) else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            description=description[:500],
            details=details or {},
            ip_address=ip,
        )
    except Exception as exc:
        logger.warning("Failed to write ActivityLog: %s", exc)


def _get_client_ip(request) -> str | None:
    """Extract client IP from request, considering reverse proxies."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
