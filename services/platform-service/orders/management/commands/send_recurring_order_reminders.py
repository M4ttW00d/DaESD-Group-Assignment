from django.core.management.base import BaseCommand
from django.utils import timezone
from orders.models import RecurringOrder
import requests
import os

NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')
SERVICE_SECRET_KEY    = os.environ.get('NOTIFICATIONS_API_SECRET_KEY') or os.environ.get('JWT_SECRET_KEY', 'change-this-secret')


class Command(BaseCommand):
    help = 'Sends a reminder notification to customers whose recurring order processes tomorrow.'

    def handle(self, *args, **options):
        tomorrow = timezone.now().date() + timezone.timedelta(days=1)

        due_tomorrow = RecurringOrder.objects.filter(
            status=RecurringOrder.Status.ACTIVE,
            next_order_date=tomorrow,
        ).select_related('customer').prefetch_related('items__product')

        count = 0
        for ro in due_tomorrow:
            customer = ro.customer
            item_names = ', '.join(
                item.product.name for item in ro.items.all()
            )
            try:
                requests.post(
                    f"{NOTIFICATIONS_API_URL}/api/notifications/",
                    json={
                        'user':    customer.id,
                        'email':   customer.email,
                        'type':    'RECURRING_ORDER_REMINDER',
                        'title':   f'Recurring Order Processing Tomorrow — #{ro.id}',
                        'message': (
                            f"Your recurring order #{ro.id} will be automatically placed tomorrow "
                            f"({tomorrow.strftime('%A, %d %B %Y')}). "
                            f"Items: {item_names}. "
                            f"If you need to make changes, please visit your recurring orders page before then."
                        ),
                    },
                    headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                    timeout=5,
                )
                count += 1
                self.stdout.write(f'Reminder sent for recurring order #{ro.id} (customer: {customer.username})')
            except Exception as e:
                self.stderr.write(f'Failed to send reminder for #{ro.id}: {e}')

        self.stdout.write(f'Done — {count} reminder(s) sent.')
