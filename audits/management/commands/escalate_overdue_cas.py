from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from audits.models import CorrectiveAction
from core.models import Notification
from audits.utils import notify_restaurant_users, notify_auditor_and_manager


class Command(BaseCommand):
    help = (
        'Escalate overdue corrective actions and auto-close stale verified ones. '
        'Run daily via cron/scheduler.'
    )

    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()

        # ---------------------------------------------------------------
        # 1. Escalate CAs past deadline + 3 days (OPEN / IN_PROGRESS)
        # ---------------------------------------------------------------
        escalation_threshold = today - timedelta(days=3)
        overdue = CorrectiveAction.objects.filter(
            deadline__lt=escalation_threshold,
            status__in=['OPEN', 'IN_PROGRESS'],
        ).select_related('audit__auditor__manager', 'restaurant', 'assigned_to')

        escalated_count = 0
        for ca in overdue:
            link = reverse('audits:corrective_action_detail', args=[ca.pk])
            title = f'ESCALATED: {ca.restaurant.name} — {ca.description[:60]}'
            message = (
                f'This {ca.get_risk_level_display().lower()} priority corrective action '
                f'is overdue by {(today - ca.deadline).days} days and requires immediate attention.'
            )
            email_context = {
                'subject': title,
                'restaurant_name': ca.restaurant.name,
                'risk_level': ca.get_risk_level_display(),
                'description': ca.description,
                'deadline': ca.deadline,
                'ca_url': link,
            }

            # Notify the restaurant users + assignee
            notify_restaurant_users(
                Notification.Type.CA_ESCALATED,
                title, message, link, ca.restaurant,
                email_context=email_context,
                extra_recipients=[ca.assigned_to] if ca.assigned_to else None,
            )

            # Notify auditors manager for escalation
            if ca.audit and ca.audit.auditor:
                notify_auditor_and_manager(
                    Notification.Type.CA_ESCALATED,
                    title, message, link, ca.audit.auditor,
                    email_context=email_context,
                )

            escalated_count += 1

        if escalated_count:
            self.stdout.write(
                self.style.WARNING(f'Escalated {escalated_count} overdue corrective actions')
            )

        # ---------------------------------------------------------------
        # 2. Auto-close stale VERIFIED CAs (verified 30+ days ago)
        # ---------------------------------------------------------------
        stale_threshold = now - timedelta(days=30)
        stale = CorrectiveAction.objects.filter(
            status='VERIFIED',
            updated_at__lt=stale_threshold,
        )

        stale_count = stale.count()
        if stale_count:
            stale.update(
                status='CLOSED',
                completion_date=today,
            )
            self.stdout.write(
                self.style.SUCCESS(f'Auto-closed {stale_count} stale verified corrective actions')
            )

        if not escalated_count and not stale_count:
            self.stdout.write(self.style.SUCCESS('No actions needed — all CA are on track'))
