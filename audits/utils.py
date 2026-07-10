from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from core.email_utils import send_notification_email
from core.models import BusinessInfo, Notification

User = get_user_model()

EMAIL_TEMPLATES = {
    Notification.Type.AUDIT_SUBMITTED: 'emails/audit_submitted.html',
    Notification.Type.CA_CREATED: 'emails/ca_created.html',
    Notification.Type.CA_COMPLETED: 'emails/ca_completed.html',
    Notification.Type.CA_VERIFIED: 'emails/ca_verified.html',
    Notification.Type.CA_CLOSED: 'emails/ca_closed.html',
    Notification.Type.CA_ESCALATED: 'emails/ca_escalated.html',
}


def _send_email_notifications(recipients, notification_type, email_context):
    """Send email copies to users who have email_notifications enabled.

    Checks both the global master toggle (BusinessInfo.email_notifications_enabled)
    and each user's personal preference (user.email_notifications).
    """
    from core.models import BusinessInfo
    info = BusinessInfo.load()
    if not info.email_notifications_enabled:
        return
    template = EMAIL_TEMPLATES.get(notification_type)
    if not template:
        return
    for user in recipients:
        if user.email_notifications and user.email:
            send_notification_email(
                recipient_email=user.email,
                subject=email_context.get('subject', 'Notification'),
                template_name=template,
                context=email_context,
            )


def auto_generate_corrective_actions(audit):
    from .models import AuditQuestionResponse, CorrectiveAction

    SLA_DAYS = {
        CorrectiveAction.RiskLevel.CRITICAL: 3,
        CorrectiveAction.RiskLevel.HIGH: 7,
        CorrectiveAction.RiskLevel.MEDIUM: 14,
        CorrectiveAction.RiskLevel.LOW: 30,
    }

    responses_needing_ca = AuditQuestionResponse.objects.filter(
        audit_section__audit=audit,
        needs_corrective_action=True,
    ).exclude(
        corrective_actions__isnull=False
    ).select_related('question', 'audit_section__section')

    # Assign to first active restaurant user of the restaurant, fallback to auditor
    restaurant_user = audit.restaurant.users.filter(role=User.Roles.RESTAURANT_USER, is_active=True).first()
    assignee = restaurant_user if restaurant_user else audit.auditor

    created = 0
    for resp in responses_needing_ca:
        is_critical = getattr(resp.question, 'is_critical', False)
        risk_level = CorrectiveAction.RiskLevel.CRITICAL if is_critical else CorrectiveAction.RiskLevel.HIGH
        description = f'{resp.audit_section.section.name}: {resp.question.question_text}'
        CorrectiveAction.objects.create(
            audit=audit,
            restaurant=audit.restaurant,
            question_response=resp,
            description=description,
            risk_level=risk_level,
            assigned_to=assignee,
            deadline=timezone.now().date() + timedelta(days=SLA_DAYS.get(risk_level, 7)),
            status=CorrectiveAction.Status.OPEN,
        )
        created += 1

    if created:
        import logging
        logger = logging.getLogger(__name__)
        logger.info('Auto-generated %d corrective actions for audit %s', created, audit.pk)

    return created


def notify_restaurant_users(notification_type, title, message, link, restaurant, email_context=None, extra_recipients=None):
    restaurant_users = restaurant.users.filter(is_active=True)
    managers = User.objects.filter(role=User.Roles.MANAGER, is_active=True)
    recipients = set(restaurant_users) | set(managers)
    if extra_recipients:
        recipients |= {u for u in extra_recipients if u}
    notifications = [
        Notification(
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
        )
        for user in recipients
    ]
    Notification.objects.bulk_create(notifications)
    if email_context:
        _send_email_notifications(recipients, notification_type, email_context)


def notify_auditor_and_manager(notification_type, title, message, link, auditor, email_context=None):
    recipients = [auditor]
    if auditor.manager and auditor.manager.is_active:
        recipients.append(auditor.manager)
    notifications = [
        Notification(
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
        )
        for user in set(recipients)
    ]
    Notification.objects.bulk_create(notifications)
    if email_context:
        _send_email_notifications(set(recipients), notification_type, email_context)
