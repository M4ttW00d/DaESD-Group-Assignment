from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('ORDER_PLACED', 'Order Placed'),
                    ('ORDER_CONFIRMED', 'Order Confirmed'),
                    ('ORDER_READY', 'Order Ready'),
                    ('ORDER_DELIVERED', 'Order Delivered'),
                    ('ORDER_CANCELLED', 'Order Cancelled'),
                    ('ORDER_UPDATE', 'Order Update'),
                    ('LOW_STOCK', 'Low Stock'),
                    ('OUT_OF_STOCK', 'Out of Stock'),
                    ('SURPLUS_DEAL', 'Surplus Deal'),
                    ('SEASONAL_REMINDER', 'Seasonal Reminder'),
                    ('PAYMENT_RECEIVED', 'Payment Received'),
                    ('SETTLEMENT_READY', 'Settlement Ready'),
                    ('GENERAL', 'General'),
                ],
                default='GENERAL',
                max_length=30,
            ),
        ),
    ]
