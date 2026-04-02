"""Stock reduction service — called on row approve."""
from __future__ import annotations

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Q

logger = logging.getLogger(__name__)


def match_distributor_product(distributor, product_value: str):
    """Find a DistributorProduct matching the given product value.

    Checks (case-insensitive): alias_sku, alias_name, product.sku, product.name.
    """
    from apps.warehouse.models import DistributorProduct

    val = product_value.strip()
    if not val:
        return None

    return (
        DistributorProduct.objects
        .filter(distributor=distributor, is_active=True)
        .filter(
            Q(alias_sku__iexact=val)
            | Q(alias_name__iexact=val)
            | Q(product__sku__iexact=val)
            | Q(product__name__iexact=val)
        )
        .select_related("product")
        .first()
    )


def _parse_qty(mapped, qty_field):
    """Parse quantity from mapped data. Returns int or None."""
    if not qty_field:
        return 1
    qty_raw = str(mapped.get(qty_field, "")).strip()
    try:
        cleaned = qty_raw.replace(",", "")
        return int(float(cleaned)) if cleaned else 1
    except (ValueError, AttributeError):
        return None


def reduce_stock_for_rows(distributor, rows: list, user, reference: str) -> dict:
    """Reduce distributor stock for approved rows, aggregated by product.

    Same product across multiple rows → single StockMovement with summed qty.
    """
    from apps.warehouse.models import (
        DistributorStock,
        MovementBatch,
        StockMovement,
        WarehouseFieldConfig,
    )

    config = WarehouseFieldConfig.load()
    if not config:
        return {"matched": 0, "unmatched": 0, "errors": [], "skipped": True}

    product_field = config.product_identifier_field
    qty_field = config.quantity_field
    results = {"matched": 0, "unmatched": 0, "errors": [], "skipped": False}

    # Aggregate qty per DistributorProduct
    dp_qty_map: dict[int, tuple] = {}  # dp.pk → (dp, total_qty)

    for row in rows:
        mapped = row.mapped_data if hasattr(row, "mapped_data") else {}
        product_value = str(mapped.get(product_field, "")).strip()

        if not product_value:
            results["unmatched"] += 1
            continue

        qty = _parse_qty(mapped, qty_field)
        if qty is None:
            results["errors"].append(f"Row {row.row_number}: invalid quantity")
            continue
        if qty <= 0:
            continue

        dp = match_distributor_product(distributor, product_value)
        if not dp:
            results["unmatched"] += 1
            continue

        if dp.pk in dp_qty_map:
            existing_dp, existing_qty = dp_qty_map[dp.pk]
            dp_qty_map[dp.pk] = (existing_dp, existing_qty + qty)
        else:
            dp_qty_map[dp.pk] = (dp, qty)

        results["matched"] += 1

    if not dp_qty_map:
        return results

    # Create one MovementBatch
    mb = MovementBatch.objects.create(
        code=MovementBatch.generate_code(),
        distributor=distributor,
        movement_type=StockMovement.TYPE_OUT,
        reference=reference,
        created_by=user,
    )

    total_qty = 0
    for dp, qty in dp_qty_map.values():
        with transaction.atomic():
            stock, _ = DistributorStock.objects.select_for_update().get_or_create(
                distributor_product=dp,
            )
            before = stock.quantity
            stock.quantity -= qty
            stock.save()

            StockMovement.objects.create(
                movement_batch=mb,
                distributor_product=dp,
                movement_type=StockMovement.TYPE_OUT,
                quantity=qty,
                quantity_before=before,
                quantity_after=stock.quantity,
                reference=reference,
                created_by=user,
            )
            total_qty += qty

    mb.total_quantity = total_qty
    mb.save(update_fields=["total_quantity"])

    return results


def reduce_stock_for_single_row(row, user) -> dict | None:
    """Reduce stock for a single approved row. Creates one MovementBatch."""
    from apps.warehouse.models import WarehouseFieldConfig

    config = WarehouseFieldConfig.load()
    if not config:
        return None

    mapped = row.mapped_data or {}
    product_value = str(mapped.get(config.product_identifier_field, "")).strip()

    if not product_value:
        return {"status": "no_product"}

    qty = _parse_qty(mapped, config.quantity_field)
    if qty is None:
        return {"status": "bad_qty"}
    if qty <= 0:
        return {"status": "zero_qty"}

    distributor = row.processing_run.batch.distributor
    reference = f"Row #{row.row_number} (Run #{row.processing_run_id})"

    # Delegate to reduce_stock_for_rows with a single-item list
    result = reduce_stock_for_rows(distributor, [row], user, reference)
    if result.get("matched", 0) > 0:
        return {"status": "ok"}
    return {"status": "no_match", "value": product_value}


def get_low_stock_alerts(user=None):
    """Return list of DistributorStock records below min threshold."""
    from apps.warehouse.models import DistributorStock, WarehouseFieldConfig

    config = WarehouseFieldConfig.load()
    if not config or config.min_stock_threshold is None:
        return []

    threshold = config.min_stock_threshold
    qs = DistributorStock.objects.select_related(
        "distributor_product__distributor",
        "distributor_product__product",
    ).filter(quantity__lte=threshold)

    if user and not (user.is_admin or user.is_superuser):
        from apps.distributors.models import get_user_distributors
        qs = qs.filter(distributor_product__distributor__in=get_user_distributors(user))

    return list(qs.order_by("quantity"))
