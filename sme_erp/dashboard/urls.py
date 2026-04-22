from django.urls import path

from .views import export_backup_csv, home, settings_view

urlpatterns = [
    path("", home, name="dashboard-home"),
    path("backup/export/csv/", export_backup_csv, name="backup-export-csv"),
    path("settings/", settings_view, name="dashboard-settings"),
]
