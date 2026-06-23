import logging

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# -----------------------------
# Role → Group sync
# -----------------------------


@receiver(post_save, sender='accounts.User')
def sync_role_to_group(sender, instance, created, **kwargs):
    role_group_map = {
        instance.Roles.ADMIN: 'Admin',
        instance.Roles.AUDITOR: 'Auditor',
        instance.Roles.MANAGER: 'Manager',
        instance.Roles.RESTAURANT_USER: 'Restaurant User',
    }
    group_name = role_group_map.get(instance.role)
    if group_name:
        group, _ = Group.objects.get_or_create(name=group_name)
        if instance.groups.count() != 1 or instance.groups.first() != group:
            instance.groups.set([group])
    else:
        if instance.groups.exists():
            instance.groups.clear()


# -----------------------------
# M2M validation
# -----------------------------


def validate_user_restaurants(sender, instance, action, **kwargs):
    if action not in ('pre_add', 'pre_remove', 'pre_clear'):
        return

    if not instance.role or instance.role == instance.Roles.ADMIN:
        return

    pk_set = kwargs.get('pk_set')
    current_count = instance.restaurants.count()

    if action == 'pre_add':
        new_count = current_count + len(pk_set)
    elif action == 'pre_remove':
        new_count = current_count - len(pk_set)
    else:
        new_count = 0

    role = instance.role
    if role == instance.Roles.RESTAURANT_USER and new_count != 1:
        raise ValidationError(
            "Restaurant user must have exactly one restaurant.")
    if role == instance.Roles.AUDITOR and new_count < 1:
        raise ValidationError(
            "Auditor must have at least one restaurant.")
    if role == instance.Roles.MANAGER and new_count > 0:
        raise ValidationError("Manager cannot have restaurants.")
