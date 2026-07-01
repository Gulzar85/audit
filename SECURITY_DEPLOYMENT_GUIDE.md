# 🔐 Security Deployment Guide
## McDonald's Audit Management System - Production Hardening

**Last Updated:** 2026-07-01  
**Status:** CRITICAL - Review before deploying to production

---

## Pre-Deployment Security Checklist

### 🔴 CRITICAL (Must Complete)

- [ ] **1. Generate New SECRET_KEY**
  ```bash
  python manage.py shell
  >>> from django.core.management.utils import get_random_secret_key
  >>> print(get_random_secret_key())
  # Copy output to .env SECRET_KEY
  ```

- [ ] **2. Generate Admin URL Token**
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  # Copy to .env ADMIN_TOKEN
  ```

- [ ] **3. Disable DEBUG Mode**
  ```
  .env: DEBUG=False
  ```

- [ ] **4. Configure SSL/TLS**
  - Set up HTTPS certificate (Let's Encrypt recommended)
  - Configure web server (nginx/Apache) for SSL
  - Test SSL configuration: https://www.ssllabs.com/ssltest/

- [ ] **5. Set ALLOWED_HOSTS**
  ```
  .env: ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
  ```

- [ ] **6. Enable Security Headers**
  ```
  Production settings already include:
  - SECURE_SSL_REDIRECT=True
  - SECURE_HSTS_SECONDS=31536000
  - SECURE_HSTS_INCLUDE_SUBDOMAINS=True
  - SECURE_HSTS_PRELOAD=True
  - SESSION_COOKIE_SECURE=True
  - SESSION_COOKIE_HTTPONLY=True
  - CSRF_COOKIE_SECURE=True
  - CSRF_COOKIE_HTTPONLY=True
  ```

- [ ] **7. Rotate Credentials**
  - Generate new EMAIL_HOST_PASSWORD
  - Update DATABASE credentials
  - Never use development credentials

- [ ] **8. Database Migration to PostgreSQL**
  ```bash
  # Production should use PostgreSQL, not SQLite
  # Install PostgreSQL and psycopg2
  pip install psycopg2-binary
  
  # Set DATABASE_URL in .env
  DATABASE_URL=postgresql://user:password@localhost/audit_db
  
  # Run migrations
  python manage.py migrate
  ```

### 🟠 HIGH PRIORITY (Must Complete Before Launch)

- [ ] **9. Rate Limiting Configuration**
  - Configured: Login (5 attempts/5 min)
  - Configured: Password reset (3 attempts/1 hour)
  - Configured: API endpoints (various thresholds)

- [ ] **10. Admin URL Hidden**
  - Admin is now at: `/secret-admin-panel-{{ ADMIN_TOKEN }}/`
  - Default `/admin/` will return 404

- [ ] **11. Email Configuration**
  ```
  .env: EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
  Test: python manage.py shell
  >>> from django.core.mail import send_mail
  >>> send_mail('Test', 'Test message', 'from@example.com', ['to@example.com'])
  ```

- [ ] **12. Security Logging**
  - Logs stored in: `logs/django.log`, `logs/error.log`, `logs/audit.log`
  - Configure log rotation and backup
  - Monitor security logs for suspicious activity

- [ ] **13. CSRF Token Verification**
  - All POST forms must include `{% csrf_token %}`
  - Template already includes this in navbar.html logout form
  - Verify in custom forms before deployment

- [ ] **14. Input Validation**
  - Query parameters validated (restaurant_id checks)
  - Form inputs validated in models and forms
  - No unescaped user input in queries

### 🟡 MEDIUM PRIORITY (Recommend Before Launch)

- [ ] **15. Two-Factor Authentication Setup**
  ```bash
  pip install django-two-factor-auth
  # Configure in settings and urls
  ```

- [ ] **16. Static Files Compression**
  ```bash
  python manage.py collectstatic --noinput
  python manage.py compress
  ```

- [ ] **17. Backup Strategy**
  - Automated database backups (daily minimum)
  - Off-site backup storage
  - Backup restoration testing

- [ ] **18. Monitoring & Alerting**
  - Set up application monitoring (Sentry, DataDog, etc.)
  - Configure alerts for errors and security events
  - Monitor disk space and database size

- [ ] **19. Web Server Security**
  - nginx: Enable security headers
  - Setup WAF (Web Application Firewall) rules
  - Configure rate limiting at web server level

- [ ] **20. API Documentation Protection**
  - Ensure API docs (if any) require authentication
  - Don't expose internal API details

---

## Deployment Steps

### Step 1: Environment Setup
```bash
# Copy environment template
cp .env.example .env

# Edit with production values
nano .env

# Verify permissions (should be read-only)
chmod 600 .env
```

### Step 2: Database Setup
```bash
# Create database
createdb audit_db

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### Step 3: Static Files
```bash
# Collect static files
python manage.py collectstatic --noinput

# Verify permissions
chmod -R 755 staticfiles/
```

### Step 4: Security Verification
```bash
# Check deployment security
python manage.py check --deploy

# Expected output should show all security checks passing
```

### Step 5: Web Server Configuration

#### Nginx Example:
```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;
    
    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "same-origin" always;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /static/ {
        alias /path/to/staticfiles/;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

### Step 6: Application Server

#### Using Gunicorn + Supervisor:
```bash
# Install
pip install gunicorn

# Create gunicorn config file
nano gunicorn_config.py
```

```python
# gunicorn_config.py
import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
max_requests = 1000
max_requests_jitter = 50
timeout = 60
```

```bash
# Test run
gunicorn -c gunicorn_config.py config.wsgi:application

# Create supervisor config
nano /etc/supervisor/conf.d/audit.conf
```

```ini
[program:audit]
command=/path/to/venv/bin/gunicorn -c /path/to/gunicorn_config.py config.wsgi:application
directory=/path/to/project
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/audit/gunicorn.log
```

### Step 7: Firewall Setup
```bash
# Open only necessary ports
sudo ufw allow 80/tcp    # HTTP (for Let's Encrypt)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 22/tcp    # SSH (restrict to your IP)
```

---

## Production Monitoring

### 1. Security Event Logging
Monitor these log files for suspicious activity:
- `logs/django.log` - General application logs
- `logs/error.log` - Errors and warnings
- `logs/audit.log` - Audit trail

### 2. Important Commands
```bash
# Check active sessions
python manage.py dumpdata sessions

# View recent errors
tail -f logs/error.log

# Monitor security logs
grep -i "failed\|error\|warning" logs/security.log

# Check database integrity
python manage.py check
```

### 3. Metrics to Monitor
- Login attempts (detect brute force)
- Failed authentication (401, 403 errors)
- Rate limit triggers (429 responses)
- Database performance (query count, response time)
- Disk space (logs and database)
- Memory usage
- CPU usage

---

## Incident Response Plan

### If Security Breach Detected:
1. **Immediate Actions**
   - Disable affected accounts
   - Kill active sessions
   - Enable enhanced logging

2. **Investigation**
   - Review logs for unusual activity
   - Check for unauthorized data access
   - Identify compromise vector

3. **Containment**
   - Rotate all credentials
   - Update SECRET_KEY
   - Reset password for all users

4. **Notification**
   - Notify affected users
   - Document incident details
   - Report to stakeholders

5. **Recovery**
   - Restore from clean backup
   - Deploy security patches
   - Implement additional controls

---

## Regular Maintenance Schedule

### Daily
- [ ] Monitor error logs
- [ ] Check disk space
- [ ] Verify backup completion

### Weekly
- [ ] Review security logs
- [ ] Check for failed login attempts
- [ ] Test backup restoration

### Monthly
- [ ] Update all dependencies
- [ ] Security audit review
- [ ] Performance tuning
- [ ] Backup integrity check

### Quarterly
- [ ] Full security assessment
- [ ] Penetration testing (if possible)
- [ ] Disaster recovery drill
- [ ] Compliance audit

### Annually
- [ ] Comprehensive security audit
- [ ] Infrastructure review
- [ ] Disaster recovery plan update
- [ ] External security audit

---

## Useful Commands

```bash
# Create new SECRET_KEY
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Generate admin token
python -c "import secrets; print(secrets.token_hex(32))"

# Run security checks
python manage.py check --deploy

# Collect static files
python manage.py collectstatic --noinput

# Create database backup
pg_dump audit_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore database from backup
psql audit_db < backup_file.sql

# Rotate logs
python manage.py logrotate

# Clear cache
python manage.py cache_clear

# View current settings
python manage.py shell
>>> from django.conf import settings
>>> print(settings.DEBUG)
```

---

## Support & Documentation

- Django Security: https://docs.djangoproject.com/en/6.0/topics/security/
- OWASP: https://owasp.org/
- Security Headers: https://securityheaders.com/
- SSL Labs: https://www.ssllabs.com/

---

**Critical Reminder:** Never skip steps marked 🔴 CRITICAL. These protections are essential for production security.

For any security concerns, immediately contact your security team.
