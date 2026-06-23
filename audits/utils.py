from django.contrib.auth import get_user_model
from django.db.models import Q

from core.models import Notification

User = get_user_model()


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
