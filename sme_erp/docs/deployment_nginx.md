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

## 5) File paths and permissions

If your project is at `/var/www/sme_erp`:

- static alias in Nginx should point to your collected static location
- service user (`www-data`) needs read access to project and static files

Example:

```bash
sudo chown -R www-data:www-data /var/www/sme_erp
```

## 6) HTTPS (recommended)

Use Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d macike.space -d www.macike.space
```

## Troubleshooting

- `502 Bad Gateway`: Gunicorn service down or socket path mismatch.
- Static files 404: wrong `alias` path or `collectstatic` not run.
- `400 Bad Request`: domain missing from `ALLOWED_HOSTS`.
