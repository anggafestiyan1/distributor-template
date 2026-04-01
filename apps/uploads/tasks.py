"""Celery tasks for upload processing."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="uploads.process_upload_batch")
def process_upload_batch(self, batch_id: int) -> None:
    """Process an uploaded file batch asynchronously."""
    from apps.uploads.models import UploadBatch
    from apps.uploads.services.pipeline import run_processing_pipeline

    logger.info("Starting process_upload_batch task for batch_id=%d", batch_id)
    try:
        run_processing_pipeline(batch_id)
    except Exception as exc:
        logger.error("process_upload_batch failed for batch_id=%d: %s", batch_id, exc)
        # Attempt retry; if max retries exceeded, the batch status remains 'error'
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("Max retries exceeded for batch_id=%d", batch_id)
            # Ensure batch is in error state
            try:
                batch = UploadBatch.objects.get(pk=batch_id)
                if batch.status != UploadBatch.STATUS_ERROR:
                    batch.status = UploadBatch.STATUS_ERROR
                    batch.error_message = str(exc)
                    batch.save(update_fields=["status", "error_message", "updated_at"])
            except Exception:
                pass


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="uploads.reprocess_upload_batch")
def reprocess_upload_batch(self, batch_id: int, reason: str, user_id: int) -> None:
    """Reprocess a batch, creating a new ProcessingRun and ReprocessLog.

    Old ProcessingRun and ImportRow records are NEVER deleted.
    """
    from apps.uploads.models import UploadBatch
    from apps.uploads.services.pipeline import run_processing_pipeline
    from apps.master_data.models import ReprocessLog

    logger.info("Starting reprocess_upload_batch for batch_id=%d reason='%s'", batch_id, reason)

    try:
        batch = UploadBatch.objects.get(pk=batch_id)
    except UploadBatch.DoesNotExist:
        logger.error("UploadBatch %d not found for reprocess", batch_id)
        return

    old_run = batch.get_latest_run()

    # Reset batch status so pipeline can proceed
    batch.status = UploadBatch.STATUS_PENDING
    batch.error_message = ""
    batch.save(update_fields=["status", "error_message", "updated_at"])

    try:
        run_processing_pipeline(batch_id)
    except Exception as exc:
        logger.error("reprocess failed for batch_id=%d: %s", batch_id, exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            pass
        return

    # Record the reprocess
    new_run = batch.get_latest_run()
    ReprocessLog.objects.create(
        batch=batch,
        triggered_by_id=user_id if user_id else None,
        reason=reason,
        old_run=old_run,
        new_run=new_run,
    )
    logger.info("Reprocess complete for batch_id=%d new_run=%s", batch_id, new_run)
