from django.db import migrations


GROUP_PERMISSIONS = {
    'Admin': '__all__',
    'Manager': {
        'view': '__all__',
        'change': ['audit', 'correctiveaction', 'restaurant'],
    },
    'Auditor': {
        'view': '__all__',
        'add': ['audit', 'auditsection', 'auditquestionresponse', 'correctiveaction'],
        'change': ['audit', 'auditsection', 'auditquestionresponse', 'correctiveaction',
                    'restaurant'],
    },
    'Restaurant User': {
        'view': ['audit', 'correctiveaction', 'restaurant'],
    },
}


def _codename(action, model_name):
    return f'{action}_{model_name}'


def _get_model_names(apps):
    names = set()
    for app_label in ('core', 'accounts', 'restaurants', 'audits'):
        try:
            config = apps.get_app_config(app_label)
            for model in config.get_models():
                names.add(model._meta.model_name)
        except LookupError:
            pass
    return names


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    all_model_names = _get_model_names(apps)

    for group_name, perm_rules in GROUP_PERMISSIONS.items():
        group, created = Group.objects.get_or_create(name=group_name)
        perms = []

        if perm_rules == '__all__':
            perms = list(Permission.objects.filter(
                content_type__app_label__in=('core', 'accounts', 'restaurants', 'audits')
            ))
        else:
            view_models = perm_rules.get('view', [])
            add_models = perm_rules.get('add', [])
            change_models = perm_rules.get('change', [])
            delete_models = perm_rules.get('delete', [])

            if view_models == '__all__':
                view_models = all_model_names

            for action, models in [
                ('view', view_models),
                ('add', add_models),
                ('change', change_models),
                ('delete', delete_models),
            ]:
                for model_name in models:
                    codename = _codename(action, model_name)
                    perm = Permission.objects.filter(
                        codename=codename,
                        content_type__app_label__in=('core', 'accounts', 'restaurants', 'audits'),
                    ).first()
                    if perm:
                        perms.append(perm)

        group.permissions.set(perms)


def delete_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUP_PERMISSIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_historicaldepartment_historicaldesignation_and_more'),
    ]

    operations = [
        migrations.RunPython(create_groups, reverse_code=delete_groups),
    ]
