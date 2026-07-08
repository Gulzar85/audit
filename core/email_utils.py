import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_notification_email(recipient_email, subject, template_name, context):
    if not recipient_email:
        logger.warning('Cannot send email — no recipient email provided')
        return

    try:
        html_message = render_to_string(template_name, context)
        plain_message = strip_tags(html_message)
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            'Failed to send email to %s (subject: %s)',
            recipient_email, subject,
        )
