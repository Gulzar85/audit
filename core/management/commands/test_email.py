import smtplib
import socket
import ssl
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Test SMTP connectivity and send a test email'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to', type=str, default='',
            help='Recipient email (defaults to EMAIL_HOST_USER)',
        )
        parser.add_argument(
            '--no-send', action='store_true',
            help='Test connection only, skip sending email',
        )

    def handle(self, *args, **options):
        host = settings.EMAIL_HOST
        port = settings.EMAIL_PORT
        user = settings.EMAIL_HOST_USER
        password = settings.EMAIL_HOST_PASSWORD
        use_tls = settings.EMAIL_USE_TLS
        timeout = getattr(settings, 'EMAIL_TIMEOUT', 30)
        recipient = options['to'] or user

        self.stdout.write(self.style.WARNING('=== SMTP Diagnostic ==='))
        self.stdout.write(f'  Host:       {host}')
        self.stdout.write(f'  Port:       {port}')
        self.stdout.write(f'  User:       {user}')
        self.stdout.write(f'  Password:   {"*" * len(password) if password else "(empty)"}')
        self.stdout.write(f'  TLS:        {use_tls}')
        self.stdout.write(f'  Timeout:    {timeout}s')
        self.stdout.write(f'  From:       {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write(f'  To:         {recipient}')
        self.stdout.write('')

        # Step 1: DNS resolution
        self.stdout.write(self.style.WARNING('[1/5] DNS resolution...'))
        try:
            ip = socket.gethostbyname(host)
            self.stdout.write(self.style.SUCCESS(f'  OK — {host} -> {ip}'))
        except socket.gaierror as e:
            self.stdout.write(self.style.ERROR(f'  FAIL — Cannot resolve {host}: {e}'))
            self._print_fix('Check DNS settings or network connectivity on PythonAnywhere')
            return

        # Step 2: TCP connection
        self.stdout.write(self.style.WARNING('[2/5] TCP connection...'))
        try:
            raw = smtplib.SMTP(host, port, timeout=timeout)
            self.stdout.write(self.style.SUCCESS(f'  OK — Connected to {host}:{port}'))
        except smtplib.SMTPConnectError as e:
            self.stdout.write(self.style.ERROR(f'  FAIL — Connection refused: {e}'))
            self._print_fix('Port may be blocked. PythonAnywhere may need to allow outbound port 587')
            return
        except socket.timeout:
            self.stdout.write(self.style.ERROR(f'  FAIL — Connection timed out after {timeout}s'))
            self._print_fix('Network timeout. Check if outbound port {port} is allowed on PythonAnywhere')
            return
        except OSError as e:
            self.stdout.write(self.style.ERROR(f'  FAIL — {e}'))
            self._print_fix('PythonAnywhere free tier blocks outbound SMTP. Upgrade to paid plan.')
            return

        try:
            # Step 3: EHLO + STARTTLS
            self.stdout.write(self.style.WARNING('[3/5] TLS handshake...'))
            raw.ehlo()
            if use_tls:
                context = ssl.create_default_context()
                raw.starttls(context=context)
                raw.ehlo()
                self.stdout.write(self.style.SUCCESS('  OK — TLS established'))
            else:
                self.stdout.write(self.style.WARNING('  SKIP — TLS disabled in settings'))

            # Step 4: Authentication
            self.stdout.write(self.style.WARNING('[4/5] Authentication...'))
            if not user or not password:
                self.stdout.write(self.style.ERROR('  FAIL — EMAIL_HOST_USER or EMAIL_HOST_PASSWORD is empty'))
                self._print_fix('Set credentials in your .env or PythonAnywhere environment variables')
                return
            try:
                raw.login(user, password)
                self.stdout.write(self.style.SUCCESS('  OK — Authenticated'))
            except smtplib.SMTPAuthenticationError as e:
                self.stdout.write(self.style.ERROR(f'  FAIL — Auth rejected: {e}'))
                self._print_fix(
                    'Office 365 rejects regular passwords when MFA is enabled.\n'
                    '  Generate an App Password at https://account.microsoft.com/security/\n'
                    '  Or ask IT to enable "Authenticated SMTP" for your mailbox.'
                )
                return

            # Step 5: Send test email
            if not options['no_send']:
                self.stdout.write(self.style.WARNING('[5/5] Sending test email...'))
                from django.core.mail import EmailMultiAlternatives
                msg = EmailMultiAlternatives(
                    subject='Audit App — SMTP Test',
                    body='This is a test email from your Django audit application.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient],
                )
                try:
                    msg.send(fail_silently=False)
                    self.stdout.write(self.style.SUCCESS(f'  OK — Email sent to {recipient}'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  FAIL — {e}'))
                    return
            else:
                self.stdout.write(self.style.WARNING('[5/5] SKIP — --no-send flag'))

            self.stdout.write(self.style.SUCCESS('\n=== All checks passed ==='))

        finally:
            try:
                raw.quit()
            except Exception:
                pass

    def _print_fix(self, msg):
        self.stdout.write(self.style.NOTICE(f'\n  Fix: {msg}'))
