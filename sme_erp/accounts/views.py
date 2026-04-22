from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import role_required
from .forms import UserCreateForm, UserUpdateForm
from .models import CustomUser
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


@login_required
@role_required("ADMIN")
def user_list_view(request):
    users = CustomUser.objects.all().order_by("username")
    return render(request, "accounts/user_list.html", {"users": users})


@login_required
@role_required("ADMIN")
def user_create_view(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data["password"])
        user.save()
        messages.success(request, f"User '{user.username}' created.")
        return redirect("accounts-users")
    return render(request, "accounts/user_form.html", {"form": form, "mode": "create"})


@login_required
@role_required("ADMIN")
def user_edit_view(request, user_id: int):
    target = get_object_or_404(CustomUser, id=user_id)
    form = UserUpdateForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        new_password = form.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
            user.save(update_fields=["password"])
        if target.id == request.user.id and not user.is_active:
            messages.error(request, "You cannot deactivate your own admin account.")
            user.is_active = True
            user.save(update_fields=["is_active"])
        messages.success(request, f"User '{user.username}' updated.")
        return redirect("accounts-users")
    return render(request, "accounts/user_form.html", {"form": form, "mode": "edit", "target_user": target})
