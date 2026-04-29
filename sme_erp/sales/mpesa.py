import base64
from datetime import datetime

import requests
from django.conf import settings


class MpesaConfigError(Exception):
    """Missing or invalid environment configuration."""


class MpesaAPIError(Exception):
    """Daraja rejected the request or returned an error payload (HTTP may still be 200)."""


def normalize_msisdn_for_daraja(raw: str) -> str:
    """Return MSISDN as 2547XXXXXXXX for Lipa na M-Pesa STK (sandbox/production)."""
    if not raw or not str(raw).strip():
        raise ValueError("Phone number is required.")
    s = str(raw).strip().replace(" ", "").replace("-", "")
    if s.startswith("+"):
        s = s[1:]
    if not s.isdigit():
        raise ValueError("Use digits only (optional country code or leading +).")
    if s.startswith("254") and len(s) == 12 and s[3] == "7":
        return s
    if s.startswith("0") and len(s) == 10 and s[1] == "7":
        return "254" + s[1:]
    if len(s) == 9 and s[0] == "7":
        return "254" + s
    raise ValueError("Use a valid Kenya mobile: 07XXXXXXXX, 2547XXXXXXXX, or +2547XXXXXXXX.")


def _raise_if_stk_error(data: object) -> None:
    if not isinstance(data, dict):
        raise MpesaAPIError("Unexpected response from M-Pesa.")
    fault = data.get("fault")
    if isinstance(fault, dict) and fault.get("faultstring"):
        raise MpesaAPIError(str(fault["faultstring"]))
    if data.get("errorMessage") or data.get("errorCode"):
        raise MpesaAPIError(str(data.get("errorMessage") or data.get("errorCode")))
    rc = data.get("ResponseCode")
    if rc is None:
        raise MpesaAPIError(str(data.get("ResponseDescription") or "Invalid M-Pesa response (no ResponseCode)."))
    if str(rc).strip() != "0":
        msg = data.get("ResponseDescription") or data.get("CustomerMessage") or "STK request was not accepted."
        raise MpesaAPIError(str(msg))
    if not data.get("CheckoutRequestID"):
        raise MpesaAPIError("M-Pesa did not return a CheckoutRequestID.")


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
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        _raise_if_stk_error(payload)
        raise MpesaAPIError(f"M-Pesa HTTP {response.status_code}: {response.text[:240]}")
    _raise_if_stk_error(payload)
    return payload
