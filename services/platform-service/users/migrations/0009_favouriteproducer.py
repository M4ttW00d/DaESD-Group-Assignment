from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_alter_user_managers_user_is_deleted'),
    ]

    operations = [
        migrations.CreateModel(
            name='FavouriteProducer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='favourite_producers',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('producer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='favourited_by',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'db_table': 'favourite_producers',
                'unique_together': {('customer', 'producer')},
            },
        ),
    ]
