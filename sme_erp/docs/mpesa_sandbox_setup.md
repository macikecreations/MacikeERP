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

## 2) Callback URL requirement

Daraja callbacks must hit a public HTTPS endpoint. For local dev, tunnel your app using a tool like ngrok and set:

`MPESA_CALLBACK_URL=https://<your-ngrok-domain>/sales/mpesa/callback/`

## 3) Sandbox checkout flow

1. Cashier selects `M-Pesa` at POS and enters phone number.
2. ERP creates pending invoice and sends STK push.
3. Daraja callback updates transaction:
   - `COMPLETED` -> invoice marked `PAID`, stock deducted.
   - `FAILED` -> invoice marked `FAILED`, stock not deducted.
