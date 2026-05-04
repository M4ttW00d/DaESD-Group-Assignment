from rest_framework import generics, permissions, status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response

from baskets.models import Basket, BasketItem
from baskets.views import IsCustomer

from .models import Order, OrderItem, CustomerOrder, RecurringOrder, RecurringOrderItem
from .serializers import OrderSerializer, CustomerOrderSerializer, RecurringOrderSerializer

from decimal import Decimal
from django.db import transaction
from collections import defaultdict
from django.utils import timezone
import datetime

import requests
import os

def calculate_delivery_date(order_date, delivery_day):
    """
    Given the date the order is placed and the desired delivery day of week,
    returns the next valid delivery date enforcing a 48-hour lead time.
    """
    days_ahead = (int(delivery_day) - int(order_date.weekday())) % 7
    if days_ahead < 2:  # if less than 48 hours away, pushes to next week
        days_ahead += 7
    return order_date + datetime.timedelta(days=days_ahead)

class OrderValidationError(Exception):
    pass

class OrderCreateView(APIView):
    """
    Handles checkout processing and order placement.
    Creates a highlevel CustomerOrder and splits into separate orders by producer.
    """
    permission_classes = [IsCustomer]

    @transaction.atomic # Transaction atomic decorator is used to rollback all database trasnactions if any of them fail
    def post(self, request):
        try:
            delivery_dates = request.data.get('delivery_dates', {})
            collection_types = request.data.get('collection_types', {})
            
            # Get customer's basket
            try:
                basket = Basket.objects.get(customer=request.user)
            except Basket.DoesNotExist:
                return Response(
                    {'error': 'Your basket is empty.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            basket_items = basket.items.select_related('product', 'product__producer').all()
            
            if not basket_items:
                return Response(
                    {'error': 'Your basket is empty.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Group by producer
            items_by_producer = defaultdict(list)
            for basket_item in basket_items:
                producer = basket_item.product.producer
                items_by_producer[producer].append(basket_item)
            
            # Create the parent/highlevel customer order
            customer_order = CustomerOrder.objects.create(
                customer=request.user
            )
            
            total_amount = Decimal('0.00')
            
            # Create separate orders for each producer
            notified_producers = []
            for producer, producer_basket_items in items_by_producer.items():
                producer_id = str(producer.id)
                delivery_date=delivery_dates.get(producer_id)
                
                try:
                    delivery_date = self._validate_delivery_date(delivery_dates.get(producer_id))
                except ValueError as e:
                    raise OrderValidationError(str(e))
                
                order = Order.objects.create(
                    customer_order=customer_order,
                    customer=request.user,
                    producer=producer,
                    delivery_date=delivery_date,
                    collection_type=collection_types.get(producer_id)
                )
                notified_producers.append(producer.id)
                
                order_subtotal = Decimal('0.00')
                
                # Create order items
                for basket_item in producer_basket_items:
                    try:
                        product = basket_item.product
                        if product.stock_quantity < basket_item.quantity:
                            raise OrderValidationError(f'Insufficient stock for {product.name}')
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=basket_item.quantity,
                            price_at_sale=product.price
                        )
                        product.stock_quantity -= basket_item.quantity
                        product.save()
                        order_subtotal += product.price * basket_item.quantity

                        low_threshold = getattr(product, 'low_stock_threshold', 10)
                        if product.stock_quantity == 0:
                            try:
                                requests.post(
                                    f"{NOTIFICATIONS_API_URL}/api/notifications/",
                                    json={
                                        'user':    producer.id,
                                        'message': f"'{product.name}' is now out of stock.",
                                        'type':    'OUT_OF_STOCK',
                                        'title':   f'Out of Stock: {product.name}',
                                    },
                                    headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                                    timeout=5
                                )
                            except Exception:
                                pass
                        elif product.stock_quantity <= low_threshold:
                            try:
                                requests.post(
                                    f"{NOTIFICATIONS_API_URL}/api/notifications/",
                                    json={
                                        'user':    producer.id,
                                        'message': (
                                            f"Low stock: '{product.name}' has only "
                                            f"{product.stock_quantity} unit(s) left."
                                        ),
                                        'type':    'LOW_STOCK',
                                        'title':   f'Low Stock: {product.name}',
                                    },
                                    headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                                    timeout=5
                                )
                            except Exception:
                                pass
                    except ValueError as e:
                        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
                
                # Update order totals
                order.total_amount = order_subtotal
                order.commission_total = order_subtotal * Decimal('0.05')
                order.save()
                
                # Add to customer order totals
                total_amount += order_subtotal
            
            # Update customer order totals
            customer_order.total_amount = total_amount
            customer_order.save()

            for producer_id in notified_producers:
                try:
                    requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/",
                        json={
                            'user':    producer_id,
                            'message': (
                                f"You have a new order from {request.user.username}. "
                                "Log in to your dashboard to view the details."
                            ),
                            'type':  'ORDER_PLACED',
                            'title': 'New Order Received',
                        },
                        headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                        timeout=5
                    )
                except Exception:
                    pass
            
            # Clear customer's basket once order is successfully placed
            basket.items.all().delete()
            
            # Return the created order
            serializer = CustomerOrderSerializer(customer_order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        except OrderValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def _validate_delivery_date(self, value):
        if value:
            parsed_date = datetime.date.fromisoformat(value)
            min_date = timezone.now().date() + datetime.timedelta(days=2)
            if parsed_date < min_date:
                raise OrderValidationError("There was an error placing your order: the delivery date must be at least 48 hours from today.")
            return parsed_date
        return value

class CustomerOrderDetailView(generics.RetrieveAPIView):
    """
    Shows a detailed order view specific to the customer.
    Returns all customer orders for an admin user.
    """
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return CustomerOrder.objects.all()
        return CustomerOrder.objects.filter(customer=user)

class CustomerOrderListView(generics.ListAPIView):
    """
    Shows a highlevel view of customer orders with actions to view
    each order's details.
    """
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == 'ADMIN':
            return CustomerOrder.objects.all()
        return CustomerOrder.objects.filter(customer=self.request.user)

class OrderListView(generics.ListAPIView):
    """
    Handles listing orders.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Order.objects.all()
        if user.role == 'PRODUCER':
            # Return orders that contain items from this producer's products
            return Order.objects.filter(producer=user).distinct()
        # Standard customers see only their own orders
        return Order.objects.filter(customer=user)

class OrderDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Order.objects.all()
        if user.role == 'PRODUCER':
            return Order.objects.filter(producer=user).distinct()
        return Order.objects.filter(customer=user)

NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')
SERVICE_SECRET_KEY    = os.environ.get('JWT_SECRET_KEY', 'change-this-secret-key-for-jwt-tokens')

class OrderStatusUpdateView(APIView):
    """
    Allows a producer to update the status of an order and log it.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role != 'PRODUCER':
            return Response({'error': 'Only producers can update status'}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            order = Order.objects.filter(pk=pk, producer=request.user).distinct().get()
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        note = request.data.get('note', '')

        if not new_status:
            return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)

        valid_statuses = [choice[0] for choice in Order.Status.choices]
        if new_status not in valid_statuses:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        # Basic progression check
        progression = ['PENDING', 'CONFIRMED', 'READY', 'DELIVERED']
        try:
            current_idx = progression.index(order.status)
            new_idx = progression.index(new_status)
            if new_idx <= current_idx:
                return Response({'error': 'Cannot revert to a previous status'}, status=status.HTTP_400_BAD_REQUEST)
            if new_idx > current_idx + 1:
                return Response({'error': 'Status cannot skip a required stage'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            pass

        # Update order status
        order.status = new_status
        order.save()

        # Create log
        from .models import OrderStatusLog
        OrderStatusLog.objects.create(
            order=order,
            producer=request.user,
            status=new_status,
            note=note
        )

        # Trigger notification to customer with a status-specific type (TC-010)
        status_type_map = {
            'CONFIRMED': 'ORDER_CONFIRMED',
            'READY':     'ORDER_READY',
            'DELIVERED': 'ORDER_DELIVERED',
            'CANCELLED': 'ORDER_CANCELLED',
        }
        notification_type = status_type_map.get(new_status, 'ORDER_UPDATE')
        try:
            requests.post(
                f"{NOTIFICATIONS_API_URL}/api/notifications/",
                json={
                    'user':    order.customer.id,
                    'message': (
                        f"Your order #{order.id} has been updated to {new_status.lower()}"
                        + (f". Note: {note}" if note else ".")
                    ),
                    'type':  notification_type,
                    'title': f'Order #{order.id} {new_status.capitalize()}',
                },
                headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                timeout=5
            )
        except Exception:
            pass  # Non-critical if notification fails

        return Response({'success': True, 'status': new_status})

class ReorderView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        try:
            customer_order = CustomerOrder.objects.get(pk=pk, customer=request.user)
        except CustomerOrder.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        basket, _ = Basket.objects.get_or_create(customer=request.user)

        added = []
        unavailable = []

        for order in customer_order.orders.all():
            for item in order.items.all():
                product = item.product

                if not product.is_available or product.stock_quantity < 1:
                    unavailable.append({
                        'product_id': product.id,
                        'product_name': product.name,
                        'reason': 'Out of stock or unavailable',
                    })
                    continue

                quantity = min(item.quantity, product.stock_quantity)

                basket_item, created = BasketItem.objects.get_or_create(
                    basket=basket,
                    product=product,
                    defaults={'quantity': quantity}
                )
                if not created:
                    new_qty = min(basket_item.quantity + quantity, product.stock_quantity)
                    basket_item.quantity = new_qty
                    basket_item.save()

                added.append({
                    'product_id': product.id,
                    'product_name': product.name,
                    'quantity': quantity,
                    'current_price': str(product.current_price),
                    'original_price': str(item.price_at_sale),
                    'price_changed': product.current_price != item.price_at_sale,
                })

        return Response({
            'added': added,
            'unavailable': unavailable,
        }, status=status.HTTP_200_OK)

class RecurringOrderCreateView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        customer_order_id = request.data.get('customer_order_id')
        
        # order_day and delivery_day are integers 0-6 for week days starting from Monday
        order_day = request.data.get('order_day')
        delivery_day = request.data.get('delivery_day')

        collection_types = request.data.get('collection_types', {})

        if order_day is None or delivery_day is None:
            return Response({'error': 'order_day and delivery_day are required.'}, status=400)
        
        # Validate 48-hour lead time
        days_between = (int(delivery_day) - int(order_day)) % 7
        if days_between == 0:
            days_between = 7
        if days_between < 2:
            return Response({
                'error': 'Delivery day must be at least 2 days after order day.'
            }, status=400)

        # Get the original customer order that the recurring order will be using as its template
        try:
            customer_order = CustomerOrder.objects.get(pk=customer_order_id, customer=request.user)
        except CustomerOrder.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        # Calculate next occurrence of order_day
        today = timezone.now().date()
        days_ahead = (int(order_day) - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # Schedule for next week if today matches
        next_order_date = today + datetime.timedelta(days=days_ahead)

        recurring_order = RecurringOrder.objects.create(
            customer=request.user,
            source_customer_order=customer_order,
            order_day=order_day,
            delivery_day=delivery_day,
            collection_types=collection_types,
            next_order_date=next_order_date,
        )

        # Snapshot the items from the source order
        for order in customer_order.orders.all():
            for item in order.items.all():
                RecurringOrderItem.objects.create(
                    recurring_order=recurring_order,
                    product=item.product,
                    quantity=item.quantity,
                )

        return Response({
            'id': recurring_order.id,
            'next_order_date': str(next_order_date),
            'order_day': recurring_order.get_order_day_display(),
            'delivery_day': recurring_order.get_delivery_day_display(),
        }, status=201)
    
class RecurringOrderListView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        recurring_orders = RecurringOrder.objects.filter(
            customer=request.user
        ).prefetch_related('items__product')
        serializer = RecurringOrderSerializer(recurring_orders, many=True)
        return Response(serializer.data)

class RecurringOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCustomer]
    serializer_class = RecurringOrderSerializer

    def get_queryset(self):
        return RecurringOrder.objects.filter(
            customer=self.request.user
        ).prefetch_related('items__product')

class RecurringOrderUpdateView(APIView):
    permission_classes = [IsCustomer]

    def patch(self, request, pk):
        try:
            ro = RecurringOrder.objects.get(pk=pk, customer=request.user)
        except RecurringOrder.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)

        if 'status' in request.data:
            new_status = request.data.get('status')
            if new_status not in [s.value for s in RecurringOrder.Status]:
                return Response({'error': 'Invalid status.'}, status=400)
            ro.status = new_status

        if 'order_day' in request.data or 'delivery_day' in request.data:
            new_order_day = int(request.data.get('order_day', ro.order_day))
            new_delivery_day = int(request.data.get('delivery_day', ro.delivery_day))

            days_between = (new_delivery_day - new_order_day) % 7
            if days_between == 0:
                days_between = 7
            if days_between < 2:
                return Response({
                    'error': 'Delivery day must be at least 2 days after order day.'
                }, status=400)

            if 'order_day' in request.data:
                ro.order_day = new_order_day
                today = timezone.now().date()
                days_ahead = (new_order_day - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                ro.next_order_date = today + datetime.timedelta(days=days_ahead)

            if 'delivery_day' in request.data:
                ro.delivery_day = new_delivery_day

        ro.save()
        return Response({'success': True})