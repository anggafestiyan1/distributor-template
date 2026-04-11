from django.urls import path

from . import views

app_name = "warehouse"

urlpatterns = [
    # Products (admin CRUD)
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/create/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/edit/", views.ProductEditView.as_view(), name="product_edit"),
    path("products/<int:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),

    # Distributor Products (assign + alias)
    path("distributor-products/", views.DistributorProductListView.as_view(), name="distributor_product_list"),
    path("distributor-products/create/", views.DistributorProductCreateView.as_view(), name="distributor_product_create"),
    path("distributor-products/<int:pk>/edit/", views.DistributorProductEditView.as_view(), name="distributor_product_edit"),
    path("distributor-products/<int:pk>/delete/", views.DistributorProductDeleteView.as_view(), name="distributor_product_delete"),

    # Distributor Stock
    path("distributor-stock/", views.DistributorStockListView.as_view(), name="distributor_stock_list"),
    path("distributor-stock/<int:pk>/adjust/", views.DistributorStockAdjustView.as_view(), name="distributor_stock_adjust"),

    # Stock Movements
    path("movements/", views.MovementBatchListView.as_view(), name="movement_list"),
    path("movements/<int:pk>/", views.MovementBatchDetailView.as_view(), name="movement_detail"),

    # Notifications
    path("notifications/", views.NotificationView.as_view(), name="notifications"),

    # Configuration
    path("config/", views.WarehouseConfigView.as_view(), name="config"),
]
