import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0007_notification_tracking_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='email_log',
                    to='notifications.notification',
                )),
                ('recipient_email', models.EmailField()),
                ('subject', models.CharField(max_length=255)),
                ('html_body', models.TextField()),
                ('status', models.CharField(
                    choices=[('SENT', 'Sent'), ('FAILED', 'Failed')],
                    default='SENT',
                    max_length=10,
                )),
                ('error_message', models.TextField(blank=True)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'email_logs',
                'ordering': ['-sent_at'],
            },
        ),
    ]
