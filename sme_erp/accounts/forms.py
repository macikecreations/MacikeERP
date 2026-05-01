from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import CustomUser


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

    class Meta:
        model = CustomUser
        fields = ["username", "email", "first_name", "last_name", "phone_number", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name == "is_active" else "form-control"
        self.fields["password"].widget.attrs["class"] = "form-control"
        self.fields["password_confirm"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class UserUpdateForm(forms.ModelForm):
    new_password = forms.CharField(widget=forms.PasswordInput, required=False, help_text="Optional: set to reset password.")
    confirm_new_password = forms.CharField(widget=forms.PasswordInput, required=False, label="Confirm New Password")

    class Meta:
        model = CustomUser
        fields = ["email", "first_name", "last_name", "phone_number", "role", "is_active", "is_staff"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name in {"is_active", "is_staff"} else "form-control"
        self.fields["new_password"].widget.attrs["class"] = "form-control"
        self.fields["confirm_new_password"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_new_password")
        if p1 or p2:
            if p1 != p2:
                self.add_error("confirm_new_password", "New passwords do not match.")
        return cleaned


class ProfilePasswordChangeForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput, label="Current Password")
    new_password = forms.CharField(widget=forms.PasswordInput, label="New Password")
    confirm_new_password = forms.CharField(widget=forms.PasswordInput, label="Confirm New Password")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_current_password(self):
        current = self.cleaned_data.get("current_password", "")
        if not self.user or not self.user.check_password(current):
            raise forms.ValidationError("Current password is incorrect.")
        return current

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_new_password")
        if p1 != p2:
            self.add_error("confirm_new_password", "New passwords do not match.")
        if p1:
            validate_password(p1, user=self.user)
        return cleaned
