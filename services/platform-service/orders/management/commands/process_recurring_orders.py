from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from collections import defaultdict
from orders.models import RecurringOrder, CustomerOrder, Order, OrderItem
from orders.views import calculate_delivery_date

class Command(BaseCommand):
    help = 'Places orders for all active recurring orders due today.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        due = RecurringOrder.objects.filter(
            status=RecurringOrder.Status.ACTIVE,
            next_order_date__lte=today
        ).prefetch_related('items__product')

        for ro in due:
            self.stdout.write(f'Processing recurring order #{ro.id}')
            try:
                self._place_order(ro, today)
            except Exception as e:
                self.stderr.write(f'Failed recurring order #{ro.id}: {e}')

    @transaction.atomic
    def _place_order(self, ro, today):
        
        # Calculate delivery date: next occurrence of delivery_day after today
        delivery_date = calculate_delivery_date(today, ro.delivery_day)

        items_by_producer = defaultdict(list)
        for item in ro.items.all():
            product = item.product
            
            # Check if fulfilling this order would bring stock to 0
            if product.stock_quantity - item.quantity == 0:
                self.stdout.write(
                    f'Warning: {product.name} will reach 0 stock after this order.'
                )
            items_by_producer[product.producer].append(item)

        # Handle cases where one or more items in the recurring order is unavailable
        if (not product.is_available) or (product.stock_quantity < item.quantity):
            ro.status = RecurringOrder.Status.PAUSED
            ro.save()
            self.stdout.write(
                f'Order #{ro.id} PAUSED - not enough stock for {product.name}. Please place the order for this week manually and unpause.'
            )
            return
        
        # Pause if none of the items are currently available as well
        elif not items_by_producer:
            ro.status = RecurringOrder.Status.PAUSED
            ro.save()
            self.stdout.write(
                f'Order #{ro.id} PAUSED - not enough stock for any item.'
            )
            return

        customer_order = CustomerOrder.objects.create(customer=ro.customer)
        total_amount = Decimal('0.00')

        for producer, items in items_by_producer.items():
            producer_id = str(producer.id)
            collection_type = ro.collection_types.get(producer_id)

            order = Order.objects.create(
                customer_order=customer_order,
                customer=ro.customer,
                producer=producer,
                delivery_date=delivery_date,
                collection_type=collection_type,
            )

            subtotal = Decimal('0.00')
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

            order.total_amount = subtotal
            order.commission_total = subtotal * Decimal('0.05')
            order.save()
            total_amount += subtotal

        customer_order.total_amount = total_amount
        customer_order.save()

        # Increase next_order_date by 7 days
        ro.next_order_date = today + timezone.timedelta(days=7)
        ro.save()