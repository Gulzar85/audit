import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse

from core.models import Notification
from .models import AuditQuestionResponse, AuditSection, Audit, CorrectiveAction
from .utils import notify_restaurant_users

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
            last_audit = Audit.objects.filter(
                restaurant=instance.restaurant,
                audit_date__lt=instance.audit_date,
                is_submitted=True
            ).order_by('-audit_date').first()

            if last_audit:
                # Update without triggering save() again to prevent recursion
                Audit.objects.filter(pk=instance.pk).update(
                    previous_audit=last_audit)
                logger.info(
                    f"Successfully linked previous audit {last_audit.pk} to {instance.pk}")
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
    notify_restaurant_users(
        Notification.Type.CA_CREATED, title, message, link, restaurant
    )
