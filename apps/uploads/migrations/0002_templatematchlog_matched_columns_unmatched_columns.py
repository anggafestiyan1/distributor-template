from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="templatematchlog",
            name="matched_columns",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="templatematchlog",
            name="unmatched_columns",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
