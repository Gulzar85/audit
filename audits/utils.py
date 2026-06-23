from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core.models import Notification

User = get_user_model()


def auto_generate_corrective_actions(audit):
    from .models import AuditQuestionResponse, CorrectiveAction

    responses_needing_ca = AuditQuestionResponse.objects.filter(
        audit_section__audit=audit,
        needs_corrective_action=True,
    ).exclude(
        corrective_actions__isnull=False
    ).select_related('question', 'audit_section__section')

    created = 0
    for resp in responses_needing_ca:
        CorrectiveAction.objects.create(
            audit=audit,
            restaurant=audit.restaurant,
            question_response=resp,
            description=f'{resp.audit_section.section.name}: {resp.question.question_text}',
            risk_level=CorrectiveAction.RiskLevel.CRITICAL,
            assigned_to=audit.auditor,
            deadline=timezone.now().date() + timedelta(days=7),
            status=CorrectiveAction.Status.OPEN,
        )
        created += 1

    if created:
        import logging
        logger = logging.getLogger(__name__)
        logger.info('Auto-generated %d corrective actions for audit %s', created, audit.pk)

    return created


def notify_restaurant_users(notification_type, title, message, link, restaurant):
    restaurant_users = restaurant.users.filter(is_active=True)
    managers = User.objects.filter(role=User.Roles.MANAGER, is_active=True)
    recipients = set(restaurant_users) | set(managers)
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


def notify_auditor_and_manager(notification_type, title, message, link, auditor):
    recipients = [auditor]
    if auditor.manager and auditor.manager.is_active:
        recipients.append(auditor.manager)
    managers = User.objects.filter(
        role=User.Roles.MANAGER, is_active=True
    ).exclude(pk__in=[u.pk for u in recipients])
    recipients.extend(managers)
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
