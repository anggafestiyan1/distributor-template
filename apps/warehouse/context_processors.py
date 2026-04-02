"""Context processor to inject low-stock alert count into every template."""


def low_stock_alerts(request):
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    from apps.warehouse.services.stock import get_low_stock_alerts
    alerts = get_low_stock_alerts(user=request.user)
    return {
        "low_stock_count": len(alerts),
    }
