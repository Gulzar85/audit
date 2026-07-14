import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from core.models import Notification
from .models import AuditQuestionResponse, AuditSection, Audit, CorrectiveAction
from .utils import notify_restaurant_users, _create_notifications

logger = logging.getLogger(__name__)

# -----------------------------
# Trigger Section Recalculation
# -----------------------------


@receiver(post_save, sender=AuditQuestionResponse)
@receiver(post_delete, sender=AuditQuestionResponse)
def recalculate_section_on_response_change(sender, instance, **kwargs):
    """
    Whenever a response is created, updated, or deleted, recalculate the parent section.
    """
    try:
        if instance.audit_section:
            instance.audit_section.calculate_section_score()
    except Exception:
        logger.exception(
            f"Signal failure: Could not recalculate AuditSection {instance.audit_section_id}")

# -----------------------------
# Trigger Audit Recalculation
# -----------------------------


@receiver(post_save, sender=AuditSection)
def recalculate_audit_on_section_change(sender, instance, **kwargs):
    """
    Whenever an AuditSection score changes, recalculate the master Audit totals.
    Note: calculate_section_score() uses update_fields, ensuring this doesn't loop infinitely.
    """
    try:
        if instance.audit:
            instance.audit.calculate_totals()
    except Exception:
        logger.exception(
            f"Signal failure: Could not recalculate Audit {instance.audit_id}")

# -----------------------------
# Link Previous Audit on Submission
# -----------------------------


@receiver(post_save, sender=Audit)
def link_previous_audit_on_submission(sender, instance, created, **kwargs):
    """
    If an audit is submitted and doesn't have a previous audit linked, find it and link it.
    """
    if instance.is_submitted and not instance.previous_audit_id:
        try:
            from django.db import transaction
            with transaction.atomic():
                locked = type(instance).objects.select_for_update().get(pk=instance.pk)
                if locked.previous_audit_id:
                    return
                last_audit = Audit.objects.filter(
                    restaurant=instance.restaurant,
                    audit_date__lt=instance.audit_date,
                    is_submitted=True
                ).order_by('-audit_date').first()
                if last_audit:
                    Audit.objects.filter(pk=instance.pk).update(
                        previous_audit=last_audit)
                    logger.info(
                        f"Linked previous audit {last_audit.pk} to {instance.pk}")
        except Exception:
            logger.exception(
                f"Signal failure: Could not link previous audit for Audit {instance.pk}")


@receiver(pre_save, sender=AuditQuestionResponse)
def validate_response_points(sender, instance, **kwargs):
    """
    Safety net: clamp scored_points to [0, possible_points] before save.
    Primary validation happens in views; this handles admin and bulk operations.
    """
    if not instance.question:
        return

    max_points = instance.question.possible_points
    if instance.scored_points > max_points:
        instance.scored_points = max_points
    if instance.scored_points < 0:
        instance.scored_points = 0


# -----------------------------
# Notification: CA Created
# -----------------------------


@receiver(post_save, sender=CorrectiveAction)
def ca_created_notification(sender, instance, created, **kwargs):
    if not created:
        return
    restaurant = instance.restaurant
    link = reverse('audits:corrective_action_edit', args=[instance.pk])
    title = f'New Corrective Action: {restaurant.name}'
    message = (
        f'A {instance.get_risk_level_display()} corrective action has been created '
        f'for {restaurant.name}.'
    )
    email_context = {
        'subject': title,
        'restaurant_name': restaurant.name,
        'risk_level': instance.get_risk_level_display(),
        'description': instance.description,
        'assigned_to': instance.assigned_to.get_full_name() or instance.assigned_to.username if instance.assigned_to else 'Unassigned',
        'deadline': instance.deadline,
        'audit_date': instance.audit.audit_date if instance.audit else None,
        'ca_url': link,
    }
    extra_recipients = [instance.audit.auditor.manager] if instance.audit.auditor and instance.audit.auditor.manager else None
    notify_restaurant_users(
        Notification.Type.CA_CREATED, title, message, link, restaurant,
        email_context=email_context,
        extra_recipients=extra_recipients,
    )


@receiver(pre_save, sender=CorrectiveAction)
def track_previous_assignment(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._prev_assigned_to_id = CorrectiveAction.objects.get(
                pk=instance.pk).assigned_to_id
        except CorrectiveAction.DoesNotExist:
            instance._prev_assigned_to_id = None
    else:
        instance._prev_assigned_to_id = None


@receiver(post_save, sender=CorrectiveAction)
def ca_reassignment_notification(sender, instance, created, **kwargs):
    prev_id = getattr(instance, '_prev_assigned_to_id', None)
    if created or prev_id == instance.assigned_to_id:
        return
    if not instance.assigned_to:
        return
    link = reverse('audits:corrective_action_edit', args=[instance.pk])
    title = f'CA Reassigned: {instance.restaurant.name}'
    message = (
        f'A {instance.get_risk_level_display()} corrective action has been reassigned to you.'
    )
    _create_notifications(
        Notification.Type.CA_CREATED, title, message, link,
        {instance.assigned_to},
        email_context={
            'subject': title,
            'restaurant_name': instance.restaurant.name,
            'risk_level': instance.get_risk_level_display(),
            'description': instance.description,
            'ca_url': link,
        },
    )


@receiver(post_save, sender=Audit)
def audit_assignment_notification(sender, instance, created, **kwargs):
    if not created or not instance.auditor:
        return
    link = reverse('audits:detail', args=[instance.pk])
    title = f'New Audit Assigned: {instance.restaurant.name}'
    message = (
        f'You have been assigned to conduct an audit at {instance.restaurant.name} '
        f'on {instance.audit_date}.'
    )
    _create_notifications(
        Notification.Type.AUDIT_SUBMITTED, title, message, link,
        {instance.auditor},
        email_context={
            'subject': title,
            'restaurant_name': instance.restaurant.name,
            'audit_date': instance.audit_date,
            'template_name': instance.template.name,
            'result_url': link,
        },
    )
