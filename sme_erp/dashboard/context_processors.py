from .models import AppSettings


def app_settings(request):
    return {"app_settings": AppSettings.get_solo()}
