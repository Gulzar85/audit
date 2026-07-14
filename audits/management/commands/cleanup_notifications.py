from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Notification


class Command(BaseCommand):
    help = 'Delete notifications older than the specified retention period.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete notifications older than this many days (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show count without deleting',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        qs = Notification.objects.filter(created_at__lt=cutoff)
        count = qs.count()

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(f'{count} notification(s) would be deleted (older than {options["days"]} days)')
            )
            return

        qs.delete()
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {count} notification(s) older than {options["days"]} days')
        )
