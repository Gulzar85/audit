# McDonald's Audit Management System

A Django-based audit management system for McDonald's Pakistan, featuring restaurant inspections, corrective action tracking, dark mode, and PDF reporting.

## Features

- **Audit Management**: Create, score, and submit restaurant audits using customizable templates
- **Corrective Actions**: Track and manage follow-up actions with deadlines and risk levels
- **Dashboard**: Real-time stats, charts, and overdue action tracking
- **PDF Reports**: Branded PDF audit reports with WeasyPrint
- **Dark Mode**: Full dark mode support with persistent user preference
- **Permissions**: Role-based access (Admin, Manager, Auditor, Restaurant User)
- **Notifications**: Automatic alerts for overdue actions and audit submissions
- **Crispy Forms**: Tailwind-styled forms via `django-crispy-forms` + `crispy-tailwind`
- **History**: Full audit trail via `django-simple-history`

## Requirements

- Python 3.11+
- Django 6.0
- WeasyPrint (for PDF generation)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/gulzar85/audit.git
cd audit

# Create virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY (any random string), DEBUG=True

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

## Configuration

Key settings in `config/settings/`:

- `base.py` — shared settings (apps, middleware, crispy template pack, etc.)
- `development.py` — local dev (SQLite, debug on)
- `production.py` — production (PostgreSQL via DATABASE_URL, debug off)

## Project Structure

```
audit/
├── accounts/          # Custom user model, auth views
├── audits/            # Core audit app (templates, scoring, CAs)
├── config/            # Django settings (base/dev/prod)
├── core/              # Shared models (notifications, mixins)
├── restaurants/       # Restaurant & region models
├── static/            # Static assets (logo, icons)
├── templates/         # Jinja/Django templates
│   ├── includes/      # Sidebar, navbar, toasts, footer
│   ├── audits/        # Audit & CA templates
│   ├── accounts/      # Auth templates (profile, users)
│   └── registration/  # Login, password reset templates
└── media/             # User-uploaded files
```

## Tests

```bash
python manage.py test
```

66 tests across audits (41), accounts (17), restaurants (8).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Django 6.0, Python 3.11 |
| Frontend | Tailwind CSS (CDN), Alpine.js 3.x, Lucide Icons, ApexCharts |
| PDF | WeasyPrint |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | Django auth + custom roles/permissions |
