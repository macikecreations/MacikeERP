# Nginx Setup (Django + Gunicorn)

This project is a Django app. In production, use:

- Nginx as reverse proxy
- Gunicorn as WSGI app server
- `collectstatic` output served directly by Nginx

## 1) Prepare Django for production

1. Set `DEBUG=False` in `config/settings.py`.
2. Ensure `ALLOWED_HOSTS` includes your domain and server IP.
3. Add static root (if not already set):

```python
STATIC_ROOT = BASE_DIR / "staticfiles"
```

4. Collect static assets:

```bash
python manage.py collectstatic --noinput
```

## 2) Install runtime packages on server

```bash
sudo apt update
sudo apt install -y nginx python3-venv
```

In your virtualenv:

```bash
pip install gunicorn
```

## 3) Create Gunicorn systemd service

Create `/etc/systemd/system/gunicorn-sme_erp.service`:

```ini
[Unit]
Description=Gunicorn for sme_erp
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/sme_erp
Environment="PATH=/var/www/sme_erp/.venv/bin"
ExecStart=/var/www/sme_erp/.venv/bin/gunicorn --workers 3 --bind unix:/run/gunicorn-sme_erp.sock config.wsgi:application

[Install]
WantedBy=multi-user.target
```

Start and enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn-sme_erp
sudo systemctl status gunicorn-sme_erp
```

## 4) Install Nginx site config

Copy this repo file:

- `deploy/nginx/sme_erp.conf`

to:

- `/etc/nginx/sites-available/sme_erp`

Then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/sme_erp /etc/nginx/sites-enabled/sme_erp
sudo nginx -t
sudo systemctl reload nginx
```

## 5) Routine deploy command summary (`/var/www/sme_erp`)

Run as your **deploy user** (the account that owns the app tree), unless noted.

```bash
cd /var/www/sme_erp
source .venv/bin/activate

# 1) Update code (pick one)
git pull
# or from your dev machine, rsync example (adjust user/host/paths):
# rsync -avz --delete \
#   --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
#   --exclude '.env' --exclude 'db.sqlite3' \
#   ./sme_erp/ myuser@erplaunch-1:/var/www/sme_erp/

# 2) Dependencies (when requirements changed)
pip install -r requirements.txt

# 3) Database schema
python manage.py migrate --noinput

# 4) Static files → STATIC_ROOT (required for /static/ in production)
python manage.py collectstatic --noinput

# 5) Restart app
sudo systemctl restart gunicorn-sme_erp

# 6) Nginx only if site config changed
sudo nginx -t && sudo systemctl reload nginx
```

**Permissions (do not `chown -R www-data` the whole project):** that breaks deploy-user writes and `collectstatic`. Use **deploy user + `www-data` group** so both can use the app directory (SQLite journals need writes in `/var/www/sme_erp`):

```bash
# One-time: so your deploy user can write group-writable dirs (re-login after)
sudo usermod -aG www-data YOUR_USER

sudo chown -R YOUR_USER:www-data /var/www/sme_erp
sudo chmod 775 /var/www/sme_erp
sudo chown www-data:www-data /var/www/sme_erp/db.sqlite3
sudo chmod 664 /var/www/sme_erp/db.sqlite3

# venv binaries must stay executable (never blanket 644 on .venv)
chmod -R u+rwX,go+rX /var/www/sme_erp/.venv
find /var/www/sme_erp/.venv/bin -type f -exec chmod 755 {} \;
```

If `collectstatic` fails with **Permission denied** creating `staticfiles/`, create it once and fix parent ownership:

```bash
sudo mkdir -p /var/www/sme_erp/staticfiles
sudo chown YOUR_USER:YOUR_USER /var/www/sme_erp/staticfiles
```

Nginx serves **`/static/`** from **`STATIC_ROOT`**: `/var/www/sme_erp/staticfiles/`. `www-data` only needs **read** on those files (normal `755`/`644` is enough).

## 6) File paths reference

- Nginx `location /static/` → **`/var/www/sme_erp/staticfiles/`** (must match `STATIC_ROOT`).
- Source assets live under `static/`; they are copied into `staticfiles/` by **`collectstatic`**.

## 7) HTTPS with Certbot (Let’s Encrypt)

Certbot’s **nginx** plugin edits your site config: it obtains certificates, adds a **`listen 443 ssl`** server block, and (by default) redirects port 80 to HTTPS.

### Prerequisites

- **DNS** for `macike.space` and `www.macike.space` must point to this server’s public IP.
- **Port 80** must reach Nginx from the internet (Let’s Encrypt HTTP-01 challenge). If you use a firewall:

```bash
sudo apt install -y ufw   # if not installed
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # opens 80 and 443
sudo ufw enable
sudo ufw status
```

- Nginx must already serve your vhost on **HTTP** (`listen 80;`) with the correct `server_name`, and `nginx -t` must pass.

### Install Certbot

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
```

### Obtain and install certificates

Non-interactive (good for docs; use your real email):

```bash
sudo certbot --nginx \
  -d macike.space -d www.macike.space \
  --non-interactive --agree-tos \
  -m you@example.com \
  --redirect
```

Interactive (prompts for email and terms):

```bash
sudo certbot --nginx -d macike.space -d www.macike.space
```

Choose redirect when asked so HTTP URLs redirect to HTTPS. Certbot stores certs under `/etc/letsencrypt/live/macike.space/` and reloads Nginx.

### Check the result

```bash
sudo nginx -t
sudo systemctl status nginx
curl -sI http://macike.space | head -n 5
curl -sI https://macike.space | head -n 5
```

### Renewal

Ubuntu installs a **systemd timer** that runs `certbot renew` twice daily. Certificates renew when within ~30 days of expiry.

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

If `renew --dry-run` succeeds, production renewals should work. Certbot reloads Nginx after a successful renew when using the nginx plugin.

### Django after HTTPS

- Keep **`ALLOWED_HOSTS`** in `.env` including `macike.space` and `www.macike.space` if you override defaults.
- Set **CSRF trusted origins** in `.env` (required for many setups once you use `https://`):

```env
CSRF_TRUSTED_ORIGINS=https://macike.space,https://www.macike.space
```

Then restart Gunicorn.

(Optional) Harden cookies behind Nginx TLS — add to `config/settings.py` when `DEBUG=False` only, e.g. gated by env:

```python
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
```

### Troubleshooting (SSL)

- **Validation failed / connection refused on port 80:** open firewall, confirm DNS, ensure no other service binds `:80`.
- **Wrong certificate / browser warning:** wrong `server_name` in nginx or hitting the default site; ensure `sites-enabled` only has your app (or correct `default_server`).
- **Renewal fails:** run `sudo certbot renew --dry-run` and read the error; fix DNS/firewall before expiry.

## Troubleshooting

- `502 Bad Gateway`: Gunicorn service down or socket path mismatch; check `203/EXEC` (missing execute on `.venv/bin/gunicorn`).
- Static files 404 / missing logo: Nginx `alias` must be `staticfiles/`, not `static/`; run **`collectstatic`** after deploy; confirm files under `/var/www/sme_erp/staticfiles/`.
- `attempt to write a readonly database`: `www-data` needs write on `db.sqlite3` and **`chmod 775`** on `/var/www/sme_erp` (SQLite journals).
- `400 Bad Request`: domain missing from `ALLOWED_HOSTS`.
- **403 CSRF on HTTPS:** add origins to `CSRF_TRUSTED_ORIGINS` (see §7).
