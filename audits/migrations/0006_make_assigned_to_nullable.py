from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audits', '0005_make_correctiveaction_question_response_nullable'),
    ]

    operations = [
        migrations.AlterField(
            model_name='correctiveaction',
            name='assigned_to',
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='historicalcorrectiveaction',
            name='assigned_to',
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
    ]
