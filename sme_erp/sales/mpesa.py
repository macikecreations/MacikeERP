import base64
from datetime import datetime

import requests
from django.conf import settings


class MpesaConfigError(Exception):
    pass


def _base_url() -> str:
    return "https://sandbox.safaricom.co.ke" if settings.MPESA_ENVIRONMENT == "sandbox" else "https://api.safaricom.co.ke"


def _validate_settings() -> None:
    required = [
        settings.MPESA_CONSUMER_KEY,
        settings.MPESA_CONSUMER_SECRET,
        settings.MPESA_SHORTCODE,
        settings.MPESA_PASSKEY,
        settings.MPESA_CALLBACK_URL,
    ]
    if not all(required):
        raise MpesaConfigError("Incomplete M-Pesa settings. Fill .env sandbox values first.")


def get_access_token() -> str:
    _validate_settings()
    auth = (settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET)
    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(url, auth=auth, timeout=settings.MPESA_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    return payload["access_token"]


def initiate_stk_push(*, phone_number: str, amount: int, account_reference: str, transaction_desc: str) -> dict:
    token = get_access_token()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode()).decode()
    body = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": settings.MPESA_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": settings.MPESA_CALLBACK_URL,
        "AccountReference": account_reference,
        "TransactionDesc": transaction_desc,
    }
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{_base_url()}/mpesa/stkpush/v1/processrequest"
    response = requests.post(url, json=body, headers=headers, timeout=settings.MPESA_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()
