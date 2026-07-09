# McDonald's Audit Management System

A Django-based QA audit management system for McDonald's Pakistan. Auditors use it on mobile devices and tablets inside restaurant kitchens to fill multi-step checklists, score sections, upload evidence images, and track corrective actions.

## Features

- **Audit Management**: Create, score, and submit restaurant audits using customizable templates with auto-save
- **Scoring Interface**: Interactive per-question pass/fail, N/A toggle, numeric scoring, auto-save, keyboard navigation
- **5-State Corrective Actions**: OPEN → IN_PROGRESS → COMPLETED → VERIFIED → CLOSED with status timeline
- **Dashboard**: ApexCharts analytics (score trends, grade distribution, gauge, section performance, CA aging, region comparison, restaurant rankings, score trends by restaurant)
- **CSV Import/Export**: Bulk import/export of regions, restaurants, users, templates, sections, and questions via Django admin (django-import-export)
- **SLA Deadlines**: Auto-calculated deadlines by risk level (Critical=3d, High=7d, Medium=14d, Low=30d)
- **Escalation Command**: Daily cron job escalates overdue CAs and auto-closes stale verified ones
- **PDF Reports**: Branded PDF audit reports via WeasyPrint
- **Role-Based Access**: Admin, Manager, Auditor, Restaurant User with granular permissions
- **Notifications**: In-app + email notifications for audit submissions and CA workflow events
- **Audit Trail**: Full history via `django-simple-history` on all core models
- **Security**: CSP headers, rate limiting, image validation, CSV injection sanitization, race condition protection

## Requirements

- Python 3.11+
- Django 6.0
- WeasyPrint (for PDF generation)

## Quick Start (Development)

```bash
# Clone the repo
git clone https://github.com/Gulzar85/audit.git
cd audit

# Create virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY (any random string)
# Ensure DJANGO_SETTINGS_MODULE is NOT set in .env (manage.py defaults to development)

# Run migrations
python manage.py migrate

# Seed demo data
python manage.py seed_data

# Create a superuser (if not seeding)
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

### Demo Credentials (after `seed_data`)

| User | Password | Role |
|------|----------|------|
| `admin` | `admin123` | Superuser |
| `manager` | `manager123` | Regional Manager |
| `auditor1` | `auditor123` | Auditor |
| `auditor2` | `auditor123` | Auditor |
| `restuser` | `rest123` | Restaurant User |

## Production Setup

### 1. Configure `.env`

```bash
cp .env.example .env
```

Set these values in `.env`:

```
SECRET_KEY=<generate a secure random key>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Email (SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=<app-password>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=audit@yourdomain.com

# Security
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
ADMIN_TOKEN=<random-hex-token>
```

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### 2. Settings & Deployment

The active settings module is controlled by the WSGI server:

| Command | Settings Used |
|---|---|
| `python manage.py runserver` | `config.settings.development` |
| Gunicorn / uWSGI (production) | `config.settings.production` |

`wsgi.py` defaults to `config.settings.production`. No `.env` variable is needed.

**Production settings** (`config/settings/production.py`) enable:
- SQLite with WAL mode and 20s busy timeout
- HSTS (1 year, include subdomains, preload)
- Secure cookies (session + CSRF)
- `HttpOnly` cookies
- `SameSite=Strict`
- Argon2 password hashing
- Content Security Policy (CDN whitelist for Alpine.js, Tailwind, Lucide, ApexCharts)
- Obfuscated admin URL via `ADMIN_TOKEN`
- Rate limiting on login (5/5min) and password reset (3/1hr)

### 3. Email Notifications

- **Global master toggle**: Django Admin → Business Info → `Email notifications enabled`
- **Per-user control**: Django Admin → Users → select users → bulk actions to enable/disable
- Users cannot toggle this themselves
- All email sending checks both the global toggle and the user's preference

### 4. Schedule the Escalation Command

Add a daily cron job to auto-escalate overdue CAs and close stale verified ones:

```bash
0 8 * * * cd /path/to/project && /path/to/venv/bin/python manage.py escalate_overdue_cas
```

### 5. Production Checklist

- [ ] `SECRET_KEY` is a unique, unpredictable value
- [ ] `DEBUG=False`
- [ ] `ALLOWED_HOSTS` set to your domain(s)
- [ ] `ADMIN_TOKEN` is a random 32+ character hex string
- [ ] HTTPS is enabled (Cloudflare, nginx, or ALB terminate SSL)
- [ ] Database is backed up regularly
- [ ] `.env` is NOT committed to version control (already in `.gitignore`)
- [ ] For multi-worker deployments, replace local-memory cache with Redis

## Project Structure

```
audit/
├── accounts/          # Custom user model, auth views, admin actions
│   └── management/commands/   # setup_groups
├── audits/            # Core audit app (scoring, CAs, dashboard, charts)
│   └── management/commands/   # seed_data, escalate_overdue_cas
├── config/            # Django settings (base/dev/prod)
│   └── settings/
├── core/              # Shared models (BusinessInfo, Notification), security middleware
├── data/              # CSV import samples (django-import-export)
│   └── import_samples/
├── restaurants/       # Restaurant & region models
├── templates/         # Django templates
│   ├── includes/      # Sidebar, navbar, toasts, footer
│   ├── audits/        # Audit & CA templates
│   ├── accounts/      # Profile, user list/detail
│   ├── components/    # Question card, UI components
│   ├── emails/        # HTML email templates
│   └── registration/  # Login, password reset templates
└── media/             # User-uploaded files (logos, evidence photos)
```

## Tests

```bash
python manage.py test
```

110 tests across audits, accounts, restaurants, and core.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Django 6.0, Python 3.11+ |
| Frontend | Tailwind CSS (CDN), Alpine.js 3.14, Lucide Icons, Font Awesome 6, ApexCharts 4.4 |
| PDF | WeasyPrint |
| Database | SQLite (WAL mode) |
| Auth | Django auth + custom roles/permissions (Admin, Manager, Auditor, Restaurant User) |
| History | django-simple-history |
| Forms | django-crispy-forms + crispy-tailwind |
| Import/Export | django-import-export |
| Security | CSP, rate limiting, Argon2 hashing, HSTS, input validation |
