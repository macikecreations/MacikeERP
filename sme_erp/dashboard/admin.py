from django.contrib import admin

from .models import AppSettings, UserPageVisit

admin.site.register(AppSettings)
admin.site.register(UserPageVisit)
