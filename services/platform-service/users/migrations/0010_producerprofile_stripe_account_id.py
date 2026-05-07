from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_favouriteproducer'),
    ]

    operations = [
        migrations.AddField(
            model_name='producerprofile',
            name='stripe_account_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Stripe connected account ID (acct_xxx) for payouts',
                max_length=255,
            ),
        ),
    ]
