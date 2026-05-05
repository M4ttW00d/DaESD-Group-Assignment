from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0013_alter_product_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='low_stock_threshold',
            field=models.PositiveIntegerField(
                default=10,
                help_text='Send a LOW_STOCK notification to the producer when stock falls to or below this value',
            ),
        ),
    ]
