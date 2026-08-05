from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from accounts.models import User, Designation, Department
from restaurants.models import Restaurant, Region
from audits.models import Audit, AuditTemplate, Section, Question, AuditSection, AuditQuestionResponse, CorrectiveAction


class Command(BaseCommand):
    help = 'Create default groups and assign permissions'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('Setting up groups and permissions...')

        # Define Groups
        roles_groups = {
            'Admin': {
                'models': [
                    (Audit, ['view', 'add', 'change', 'delete']),
                    (AuditTemplate, ['view', 'add', 'change', 'delete']),
                    (Section, ['view', 'add', 'change', 'delete']),
                    (Question, ['view', 'add', 'change', 'delete']),
                    (AuditSection, ['view', 'add', 'change', 'delete']),
                    (AuditQuestionResponse, ['view', 'add', 'change', 'delete']),
                    (CorrectiveAction, ['view', 'add', 'change', 'delete']),
                    (Restaurant, ['view', 'add', 'change', 'delete']),
                    (Region, ['view', 'add', 'change', 'delete']),
                    (User, ['view', 'add', 'change', 'delete']),
                    (Designation, ['view', 'add', 'change', 'delete']),
                    (Department, ['view', 'add', 'change', 'delete']),
                ]
            },
            'Manager': {
                'models': [
                    (Audit, ['view']),
                    (AuditTemplate, ['view']),
                    (Section, ['view']),
                    (Question, ['view']),
                    (AuditSection, ['view']),
                    (AuditQuestionResponse, ['view']),
                    (CorrectiveAction, ['view', 'add', 'change', 'delete']),
                    (Restaurant, ['view']),
                    (Region, ['view']),
                    (User, ['view']),
                    (Designation, ['view']),
                    (Department, ['view']),
                ]
            },
            'Auditor': {
                'models': [
                    (Audit, ['view', 'add', 'change', 'delete']),
                    (AuditTemplate, ['view']),
                    (Section, ['view']),
                    (Question, ['view']),
                    (AuditSection, ['view']),
                    (AuditQuestionResponse, ['view', 'change']),
                    (CorrectiveAction, ['view', 'add', 'change', 'delete']),
                    (Restaurant, ['view']),
                    (Region, ['view']),
                    (Designation, ['view']),
                    (Department, ['view']),
                ]
            },
            'Restaurant User': {
                'models': [
                    (Audit, ['view']),
                    (AuditSection, ['view']),
                    (AuditQuestionResponse, ['view']),
                    (CorrectiveAction, ['view', 'change']),
                    (Restaurant, ['view']),
                    (Designation, ['view']),
                    (Department, ['view']),
                ]
            }
        }

        for group_name, config in roles_groups.items():
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(f"Created group: {group_name}")
            else:
                self.stdout.write(f"Group already exists, updating permissions: {group_name}")

            permissions_to_add = []
            for model_class, actions in config['models']:
                content_type = ContentType.objects.get_for_model(model_class)
                for action in actions:
                    codename = f"{action}_{model_class._meta.model_name}"
                    try:
                        perm = Permission.objects.get(content_type=content_type, codename=codename)
                        permissions_to_add.append(perm)
                    except Permission.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f"Permission not found: {codename}"))

            group.permissions.set(permissions_to_add)
            self.stdout.write(self.style.SUCCESS(f"  OK: Assigned {len(permissions_to_add)} permissions to {group_name}"))

        self.stdout.write(self.style.SUCCESS('Successfully configured groups and permissions.'))
