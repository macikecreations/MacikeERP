# M-Pesa Daraja Sandbox Setup

This project is configured for Daraja sandbox checkout only.

## 1) Fill `.env`

Edit `/.env` and set:

- `MPESA_ENVIRONMENT=sandbox`
- `MPESA_CONSUMER_KEY=<your_sandbox_consumer_key>`
- `MPESA_CONSUMER_SECRET=<your_sandbox_consumer_secret>`
- `MPESA_SHORTCODE=174379` (default sandbox shortcode)
- `MPESA_PASSKEY=<sandbox_lipa_na_mpesa_passkey>`
- `MPESA_CALLBACK_URL=<public_https_url>/sales/mpesa/callback/`
- `MPESA_TIMEOUT_SECONDS=30`
- `ALLOWED_HOSTS=127.0.0.1,localhost,<your-ngrok-host>` — required so Django accepts callbacks when using ngrok (no spaces between hosts).

## 2) Callback URL requirement

Daraja callbacks must hit a public HTTPS endpoint. For local dev, tunnel your app using **ngrok** and set:

`MPESA_CALLBACK_URL=https://<your-ngrok-domain>/sales/mpesa/callback/`

**Common mistake:** the path must be exactly `/sales/mpesa/callback/` (Django mounts the sales app at `/sales/`). A URL like `/mpesa/daraja/callback/` will 404 and M-Pesa will never update the invoice.

### Using ngrok (quick)

1. [Sign up / install ngrok](https://ngrok.com/download) and add your auth token once: `ngrok config add-authtoken <token>`.
2. Start Django: `python manage.py runserver` (default port **8000**).
3. In another terminal: `ngrok http 8000`
4. Copy the **HTTPS** “Forwarding” URL (e.g. `https://abc-123.ngrok-free.app`).
5. Set in `.env`:
   - `MPESA_CALLBACK_URL=https://abc-123.ngrok-free.app/sales/mpesa/callback/`
   - `ALLOWED_HOSTS=127.0.0.1,localhost,abc-123.ngrok-free.app`
6. **Restart** `runserver` after editing `.env`.
7. In the Daraja portal, if it asks for a callback/validation URL, use the same HTTPS base or the exact callback path above.

Free ngrok URLs change each time you restart ngrok unless you use a **reserved domain**—update `.env` and Daraja when the URL changes.

**Windows shortcut:** from the project folder, with Django running on port 8000, double‑click `scripts/dev_with_ngrok.bat` (or run the `.ps1`). It starts ngrok if needed and rewrites `MPESA_CALLBACK_URL` and `ALLOWED_HOSTS` in `.env`; then restart `runserver`.

## 3) Sandbox checkout flow

1. Cashier selects `M-Pesa` at POS and enters phone number (`07XXXXXXXX`, `2547XXXXXXXX`, or `+2547XXXXXXXX`; normalized to `2547…` for Daraja).
2. ERP creates a **pending** invoice, calls STK **outside** the DB transaction, then stores `CheckoutRequestID` on `MpesaTransaction`.
3. If Daraja rejects the STK request (or the network fails), the invoice is marked `FAILED` so stock is not left in limbo.
4. Daraja POSTs to `/sales/mpesa/callback/`:
   - **Success** (`ResultCode` 0): M-Pesa row `COMPLETED`, invoice `PAID`, FIFO stock deducted.
   - **Failure**: M-Pesa row `FAILED`; invoice `FAILED` only if it was still `PENDING_PAYMENT`.

## 4) Daraja sandbox phone

Use the **sandbox test MSISDN** from your Daraja developer portal (often documented as a test number for STK). Real numbers only work in production with a production app.
