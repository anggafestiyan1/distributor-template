from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("log/", views.MainLogView.as_view(), name="main_log"),
    path("settings-log/", views.SettingsLogView.as_view(), name="settings_log"),
]
