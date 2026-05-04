from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_notificationpreference'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationTypePreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.IntegerField(db_index=True)),
                ('notification_type', models.CharField(max_length=50)),
                ('email_enabled', models.BooleanField(default=True)),
                ('in_app_enabled', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'notification_type_preferences',
            },
        ),
        migrations.AlterUniqueTogether(
            name='notificationtypepreference',
            unique_together={('user_id', 'notification_type')},
        ),
    ]
