from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from sales.models import SalesInvoice
from inventory.models import StockAuditLog


class ERPLoginView(LoginView):
    template_name = "registration/login.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        return form


class ERPLogoutView(LogoutView):
    http_method_names = ["get", "post", "options"]


@login_required
def profile_view(request):
    recent_invoices = SalesInvoice.objects.filter(cashier=request.user)[:10]
    recent_activity = StockAuditLog.objects.filter(user=request.user)[:10]
    return render(
        request,
        "accounts/profile.html",
        {"recent_invoices": recent_invoices, "recent_activity": recent_activity},
    )
