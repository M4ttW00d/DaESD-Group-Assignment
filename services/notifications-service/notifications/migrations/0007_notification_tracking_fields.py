from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0006_add_recurring_order_notification_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='show_in_app',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='email_sent',
            field=models.BooleanField(default=False),
        ),
    ]
