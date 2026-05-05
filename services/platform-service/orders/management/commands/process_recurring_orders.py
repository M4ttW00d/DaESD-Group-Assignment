from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from collections import defaultdict
from orders.models import RecurringOrder, CustomerOrder, Order, OrderItem
from orders.views import calculate_delivery_date
import requests
import os
import sys

NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')
SERVICE_SECRET_KEY    = os.environ.get('NOTIFICATIONS_API_SECRET_KEY') or os.environ.get('JWT_SECRET_KEY', 'change-this-secret')


def _notify(user_id, email, notification_type, title, message):
    try:
        resp = requests.post(
            f"{NOTIFICATIONS_API_URL}/api/notifications/",
            json={
                'user':    user_id,
                'email':   email,
                'type':    notification_type,
                'title':   title,
                'message': message,
            },
            headers={'X-Service-Secret': SERVICE_SECRET_KEY},
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            print(f'[_notify] WARN {notification_type} → HTTP {resp.status_code}: {resp.text[:300]}', file=sys.stderr)
    except Exception as e:
        print(f'[_notify] ERROR {notification_type}: {e}', file=sys.stderr)


class Command(BaseCommand):
    help = 'Places orders for all active recurring orders due today.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        due = RecurringOrder.objects.filter(
            status=RecurringOrder.Status.ACTIVE,
            next_order_date__lte=today
        ).prefetch_related('items__product', 'customer')

        for ro in due:
            self.stdout.write(f'Processing recurring order #{ro.id}')
            try:
                self._place_order(ro, today)
            except Exception as e:
                self.stderr.write(f'Failed recurring order #{ro.id}: {e}')

    @transaction.atomic
    def _place_order(self, ro, today):
        customer       = ro.customer
        customer_email = customer.email
        customer_id    = customer.id

        delivery_date = calculate_delivery_date(today, ro.delivery_day)

        items_by_producer = defaultdict(list)
        unavailable_items = []

        for item in ro.items.all():
            product = item.product

            if (not product.is_available) or (product.stock_quantity < item.quantity):
                unavailable_items.append(product.name)
            else:
                items_by_producer[product.producer].append(item)

                if product.stock_quantity - item.quantity == 0:
                    self.stdout.write(
                        f'Warning: {product.name} will reach 0 stock after this order.'
                    )

        if unavailable_items:
            ro.status = RecurringOrder.Status.PAUSED
            ro.save()
            names = ', '.join(unavailable_items)
            self.stdout.write(
                f'Recurring order #{ro.id} PAUSED — unavailable: {names}'
            )
            _notify(
                user_id=customer_id,
                email=customer_email,
                notification_type='RECURRING_ORDER_PAUSED',
                title=f'Recurring Order #{ro.id} Paused',
                message=(
                    f"Your recurring order #{ro.id} has been paused because the following "
                    f"item(s) are currently unavailable or out of stock: {names}. "
                    f"Please visit your orders page to review and manually place this week's order, "
                    f"then unpause the recurring order when you're ready."
                ),
            )
            return

        if not items_by_producer:
            ro.status = RecurringOrder.Status.PAUSED
            ro.save()
            self.stdout.write(f'Recurring order #{ro.id} PAUSED — no available items.')
            _notify(
                user_id=customer_id,
                email=customer_email,
                notification_type='RECURRING_ORDER_PAUSED',
                title=f'Recurring Order #{ro.id} Paused',
                message=(
                    f"Your recurring order #{ro.id} has been paused because none of the "
                    f"items are currently available. Please review your order and unpause when ready."
                ),
            )
            return

        customer_order = CustomerOrder.objects.create(customer=customer)
        total_amount   = Decimal('0.00')
        summary_lines  = []

        for producer, items in items_by_producer.items():
            producer_id    = str(producer.id)
            collection_type = ro.collection_types.get(producer_id)

            order = Order.objects.create(
                customer_order=customer_order,
                customer=customer,
                producer=producer,
                delivery_date=delivery_date,
                collection_type=collection_type,
            )

            subtotal      = Decimal('0.00')
            producer_display = getattr(getattr(producer, 'producer_profile', None), 'business_name', None) or producer.username
            producer_lines = [f"\n{producer_display}:"]
            for item in items:
                product = item.product
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=item.quantity,
                    price_at_sale=product.current_price,
                )
                product.stock_quantity -= item.quantity
                product.save()
                subtotal += product.current_price * item.quantity
                producer_lines.append(f"  • {product.name} x{item.quantity} — £{product.current_price}")

            order.total_amount = subtotal
            order.commission_total = subtotal * Decimal('0.05')
            order.save()
            total_amount += subtotal
            summary_lines.extend(producer_lines)

            _notify(
                user_id=producer.id,
                email=producer.email,
                notification_type='ORDER_PLACED',
                title=f'New Recurring Order — #{order.id}',
                message=(
                    f"A recurring order from {customer.username} has been automatically placed. "
                    f"Sub-order #{order.id} — your total: £{subtotal:.2f}.\n"
                    + "\n".join(producer_lines[1:])
                    + (f"\nDelivery date: {delivery_date}" if delivery_date else "")
                ),
            )

        customer_order.total_amount = total_amount
        customer_order.save()

        ro.next_order_date = today + timezone.timedelta(days=7)
        ro.save()

        self.stdout.write(f'Recurring order #{ro.id} placed → customer order #{customer_order.id}')

        order_summary = (
            f"Order #{customer_order.id} — Total: £{total_amount:.2f}"
            + "".join(summary_lines)
            + (f"\n\nDelivery date: {delivery_date}" if delivery_date else "")
            + f"\n\nYour next recurring order is scheduled for {ro.next_order_date}."
        )
        _notify(
            user_id=customer_id,
            email=customer_email,
            notification_type='RECURRING_ORDER_PLACED',
            title=f'Recurring Order Placed — #{customer_order.id}',
            message=order_summary,
        )
