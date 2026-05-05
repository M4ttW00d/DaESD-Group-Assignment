from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_alter_payment_options_payment_currency_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='settled',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='WeeklySettlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('week_start', models.DateField()),
                ('week_end', models.DateField()),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Pending'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')],
                    default='PENDING',
                    max_length=20,
                )),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'weekly_settlements',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProducerSettlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('settlement', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='producer_settlements',
                    to='payments.weeklysettlement',
                )),
                ('producer_id', models.CharField(blank=True, default='', max_length=64)),
                ('producer_name', models.CharField(blank=True, default='', max_length=255)),
                ('stripe_account_id', models.CharField(blank=True, default='', max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('transfer_id', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Pending'), ('TRANSFERRED', 'Transferred'), ('SKIPPED', 'Skipped'), ('FAILED', 'Failed')],
                    default='PENDING',
                    max_length=20,
                )),
                ('error_message', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'producer_settlements',
            },
        ),
    ]
