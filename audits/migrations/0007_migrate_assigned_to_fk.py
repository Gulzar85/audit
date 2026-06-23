from django.db import migrations, models
import django.db.models.deletion


def clear_assigned_to(apps, schema_editor):
    CorrectiveAction = apps.get_model('audits', 'CorrectiveAction')
    CorrectiveAction.objects.exclude(assigned_to__isnull=True).exclude(assigned_to__exact='').update(assigned_to=None)
    HistoricalCorrectiveAction = apps.get_model('audits', 'HistoricalCorrectiveAction')
    if HistoricalCorrectiveAction.objects.exists():
        HistoricalCorrectiveAction.objects.exclude(assigned_to__isnull=True).exclude(assigned_to__exact='').update(assigned_to=None)


class Migration(migrations.Migration):

    dependencies = [
        ('audits', '0006_make_assigned_to_nullable'),
    ]

    operations = [
        migrations.RunPython(clear_assigned_to, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='correctiveaction',
            name='assigned_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_cas', to='accounts.user'),
        ),
        migrations.AlterField(
            model_name='historicalcorrectiveaction',
            name='assigned_to',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='accounts.user'),
        ),
    ]
