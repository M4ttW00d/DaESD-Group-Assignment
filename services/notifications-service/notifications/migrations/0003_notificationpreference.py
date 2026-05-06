from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_add_seasonal_reminder_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.IntegerField(db_index=True, unique=True)),
                ('email_enabled', models.BooleanField(default=True)),
                ('in_app_enabled', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'notification_preferences',
            },
        ),
    ]
