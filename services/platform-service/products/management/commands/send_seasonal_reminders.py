import os
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from products.models import Product

NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')
SERVICE_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'change-this-secret-key-for-jwt-tokens')


class Command(BaseCommand):
    help = 'Notify producers whose seasonal products are coming into season within 1 month.'

    def handle(self, *args, **options):
        current_month = timezone.now().month
        next_month = current_month % 12 + 1

        products = Product.objects.filter(
            seasonal_start_month=next_month,
            is_available=True,
        ).select_related('producer')

        notified_pairs = set()
        sent = 0

        for product in products:
            producer = product.producer
            key = (producer.id, product.id)
            if key in notified_pairs:
                continue
            notified_pairs.add(key)

            months = {
                1: 'January', 2: 'February', 3: 'March', 4: 'April',
                5: 'May', 6: 'June', 7: 'July', 8: 'August',
                9: 'September', 10: 'October', 11: 'November', 12: 'December',
            }
            season_month_name = months.get(next_month, str(next_month))

            try:
                requests.post(
                    f"{NOTIFICATIONS_API_URL}/api/notifications/",
                    json={
                        'user': producer.id,
                        'type': 'SEASONAL_REMINDER',
                        'title': f"Season Starting: {product.name}",
                        'message': (
                            f"Your product '{product.name}' comes into season in "
                            f"{season_month_name}. Make sure your stock is ready for customers!"
                        ),
                    },
                    headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                    timeout=5,
                )
                sent += 1
            except Exception:
                self.stderr.write(f"Failed to notify producer {producer.id} for product {product.id}")

        self.stdout.write(f"Seasonal reminders sent: {sent}")
