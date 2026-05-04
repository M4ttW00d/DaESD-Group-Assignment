from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from baskets.models import Basket
from baskets.views import IsCustomer

from .models import Order, OrderItem, CustomerOrder
from .serializers import OrderSerializer, CustomerOrderSerializer

from decimal import Decimal
from django.db import transaction
from collections import defaultdict

import requests
import os


class OrderCreateView(APIView):
    """
    Handles checkout processing and order placement.
    Creates a highlevel CustomerOrder and splits into separate orders by producer.
    """
    permission_classes = [IsCustomer]

    @transaction.atomic # Transaction atomic decorator is used to rollback all database trasnactions if any of them fail
    def post(self, request):
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
            order = Order.objects.create(
                customer_order=customer_order,
                customer=request.user,
                producer=producer,
                delivery_date=delivery_dates.get(producer_id),
                collection_type=collection_types.get(producer_id)
            )
            notified_producers.append(producer.id)

            order_subtotal = Decimal('0.00')
            
            # Create order items
            for basket_item in producer_basket_items:
                try:
                    product = basket_item.product
                    if product.stock_quantity < basket_item.quantity:
                        raise ValueError(f'Insufficient stock for {product.name}')
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
