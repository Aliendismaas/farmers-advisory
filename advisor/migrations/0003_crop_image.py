from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("advisor", "0002_advisoryrule_weatherdatasource_farmerprofile_role_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="crop",
            name="image",
            field=models.ImageField(
                blank=True,
                help_text="Optional photo shown in the crop library and detail page",
                upload_to="crops/",
            ),
        ),
    ]
