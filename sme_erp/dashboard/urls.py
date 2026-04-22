from django.urls import path

from .views import export_backup_csv, home

urlpatterns = [
    path("", home, name="dashboard-home"),
    path("backup/export/csv/", export_backup_csv, name="backup-export-csv"),
]
