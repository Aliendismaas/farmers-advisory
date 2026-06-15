from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('advisor', '0005_password_reset_otp'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationpreference',
            name='language',
            field=models.CharField(
                choices=[('en', 'English'), ('sw', 'Kiswahili')],
                default='en',
                help_text='Language for advisory SMS messages.',
                max_length=4,
            ),
        ),
    ]
