from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0014_product_low_stock_threshold'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='seasonal_reminder_sent_month',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='seasonal_reminder_sent_year',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
