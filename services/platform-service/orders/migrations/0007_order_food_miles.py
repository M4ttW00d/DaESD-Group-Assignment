from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0006_order_is_deleted_orderitem_is_deleted'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='food_miles',
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text='Distance in miles from producer to customer, calculated at order placement. Null for collection orders.',
                max_digits=8,
                null=True,
            ),
        ),
    ]
