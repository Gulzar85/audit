from django.db import migrations, models


def migrate_completed_to_status(apps, schema_editor):
    CorrectiveAction = apps.get_model('audits', 'CorrectiveAction')
    CorrectiveAction.objects.filter(completed=True).update(status='COMPLETED')
    HistoricalCorrectiveAction = apps.get_model('audits', 'HistoricalCorrectiveAction')
    if HistoricalCorrectiveAction.objects.exists():
        HistoricalCorrectiveAction.objects.filter(completed=True).update(status='COMPLETED')


class Migration(migrations.Migration):

    dependencies = [
        ('audits', '0007_migrate_assigned_to_fk'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='correctiveaction',
            name='audits_corr_restaur_86875e_idx',
        ),
        migrations.AddField(
            model_name='correctiveaction',
            name='status',
            field=models.CharField(choices=[('OPEN', 'Open'), ('IN_PROGRESS', 'In Progress'), ('COMPLETED', 'Completed'), ('VERIFIED', 'Verified'), ('CLOSED', 'Closed')], default='OPEN', max_length=20),
        ),
        migrations.AddField(
            model_name='historicalcorrectiveaction',
            name='status',
            field=models.CharField(choices=[('OPEN', 'Open'), ('IN_PROGRESS', 'In Progress'), ('COMPLETED', 'Completed'), ('VERIFIED', 'Verified'), ('CLOSED', 'Closed')], default='OPEN', max_length=20),
        ),
        migrations.RunPython(migrate_completed_to_status, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='correctiveaction',
            name='completed',
        ),
        migrations.RemoveField(
            model_name='historicalcorrectiveaction',
            name='completed',
        ),
        migrations.AddIndex(
            model_name='correctiveaction',
            index=models.Index(fields=['restaurant', 'status'], name='audits_corr_restaur_b34703_idx'),
        ),
    ]
