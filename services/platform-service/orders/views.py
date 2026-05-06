from rest_framework import generics, permissions, status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response

from baskets.models import Basket, BasketItem
from baskets.views import IsCustomerOrCommunityRepresentative

from .models import Order, OrderItem, CustomerOrder, RecurringOrder, RecurringOrderItem, OrderStatusLog
from .serializers import OrderSerializer, CustomerOrderSerializer, RecurringOrderSerializer

from decimal import Decimal
from collections import defaultdict
from io import StringIO

from django.db import transaction
from django.utils import timezone
from django.core.management import call_command

import datetime
import math
import requests

def _get_postcode_coords(postcode, _cache={}):
    """Fetch lat/lng for a UK postcode from postcodes.io. Caches results."""
    if not postcode:
        return None, None
    key = postcode.strip().upper().replace(' ', '')
    if key in _cache:
        return _cache[key]
    try:
        resp = requests.get(
            f"https://api.postcodes.io/postcodes/{postcode.strip().replace(' ', '%20')}",
            timeout=5
        )
        if resp.status_code == 200:
            result = resp.json().get('result') or {}
            coords = result.get('latitude'), result.get('longitude')
            _cache[key] = coords
            return coords
    except Exception:
        pass
    _cache[key] = (None, None)
    return None, None

def _calculate_food_miles(customer_postcode, producer_postcode):
    """Calculate straight-line distance in miles between two postcodes."""
    if not customer_postcode or not producer_postcode:
        return None
    lat1, lon1 = _get_postcode_coords(customer_postcode)
    lat2, lon2 = _get_postcode_coords(producer_postcode)
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 1)
import os

def calculate_delivery_date(order_date, delivery_day):
    days_ahead = (int(delivery_day) - int(order_date.weekday())) % 7
    if days_ahead < 2:
        days_ahead += 7
    return order_date + datetime.timedelta(days=days_ahead)

def is_in_season(product):
    season_start = product.seasonal_start_month
    season_end = product.seasonal_end_month

    if season_start is None or season_end is None:
        return True

    current_month = timezone.now().date().month

    return season_start <= current_month <= season_end

class OrderValidationError(Exception):
    pass

class OrderCreateView(APIView):
    """
    Handles checkout processing and order placement.
    Creates a highlevel CustomerOrder and splits into separate orders by producer.
    """
    permission_classes = [IsCustomerOrCommunityRepresentative]

    @transaction.atomic
    def post(self, request):
        try:
            delivery_dates = request.data.get('delivery_dates', {})
            collection_types = request.data.get('collection_types', {})
            delivery_instructions = request.data.get('delivery_instructions', {})

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

            items_by_producer = defaultdict(list)
            for basket_item in basket_items:
                producer = basket_item.product.producer
                items_by_producer[producer].append(basket_item)

            customer_order = CustomerOrder.objects.create(
                customer=request.user
            )

            total_amount = Decimal('0.00')

            for producer, producer_basket_items in items_by_producer.items():
                producer_id = str(producer.id)
                delivery_date=delivery_dates.get(producer_id)
                delivery_instruction=delivery_instructions.get(producer_id)

                try:
                    delivery_date = self._validate_delivery_date(delivery_dates.get(producer_id))
                except ValueError as e:
                    raise OrderValidationError(str(e))

                # Calculate food miles for delivery orders only
                collection_type = collection_types.get(producer_id, '')
                food_miles = None
                if collection_type and 'collect' not in collection_type.lower():
                    try:
                        customer_postcode = (
                            getattr(request.user, 'customer_profile', None) and request.user.customer_profile.postcode
                            or getattr(request.user, 'community_profile', None) and request.user.community_profile.postcode
                        )
                        producer_postcode = producer.producer_profile.postcode
                        food_miles = _calculate_food_miles(customer_postcode, producer_postcode)
                    except Exception:
                        pass


                order = Order.objects.create(
                    customer_order=customer_order,
                    customer=request.user,
                    producer=producer,
                    delivery_date=delivery_date,
                    collection_type=collection_type,
                    delivery_instruction=delivery_instruction,
                    food_miles=food_miles,
                )

                order_subtotal = Decimal('0.00')

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
                                        'email':   producer.email,
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
                                        'email':   producer.email,
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

                order.total_amount = order_subtotal
                order.commission_total = order_subtotal * Decimal('0.05')
                order.save()

                total_amount += order_subtotal

                is_bulk = getattr(request.user, 'role', '') == 'COMMUNITY-GROUP-REPRESENTATIVE'
                notif_type = 'BULK_ORDER_PLACED' if is_bulk else 'ORDER_PLACED'

                order_lines = [f"Order #{order.id} from {request.user.username}\n"]
                if is_bulk:
                    try:
                        org_name = request.user.community_profile.organisation_name
                        order_lines[0] = f"Bulk Order #{order.id} from {request.user.username} ({org_name})\n"
                    except Exception:
                        order_lines[0] = f"Bulk Order #{order.id} from {request.user.username} (Community Group)\n"
                for basket_item in producer_basket_items:
                    product = basket_item.product
                    order_lines.append(f"  • {product.name} x{basket_item.quantity} — £{product.price}")
                order_lines.append(f"\nSubtotal: £{order_subtotal:.2f}")
                collection = collection_types.get(producer_id)
                if collection:
                    order_lines.append(f"Collection type: {collection}")
                if delivery_date:
                    order_lines.append(f"Delivery date: {delivery_date}")
                if is_bulk and delivery_instruction:
                    order_lines.append(f"\nSpecial Instructions: {delivery_instruction}")
                if is_bulk:
                    order_lines.append(f"\nCustomer Contact Details:")
                    order_lines.append(f"  Email: {request.user.email}")
                    if request.user.phone_number:
                        order_lines.append(f"  Phone: {request.user.phone_number}")
                    try:
                        delivery_addr = request.user.community_profile.delivery_address
                        if delivery_addr:
                            order_lines.append(f"  Delivery Address: {delivery_addr}")
                    except Exception:
                        pass

                notif_title = (
                    f'Bulk Order Received — #{order.id}' if is_bulk
                    else f'New Order Received — #{order.id}'
                )

                try:
                    requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/",
                        json={
                            'user':    producer.id,
                            'email':   producer.email,
                            'message': "\n".join(order_lines),
                            'type':    notif_type,
                            'title':   notif_title,
                        },
                        headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                        timeout=5
                    )
                except Exception:
                    pass

            customer_order.total_amount = total_amount
            customer_order.save()

            basket.items.all().delete()

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
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return CustomerOrder.objects.all()
        return CustomerOrder.objects.filter(customer=user)
    
class CustomerOrderCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            customer_order = CustomerOrder.objects.get(pk=pk, customer=request.user)
            
            if not customer_order.can_cancel:
                return Response(
                    {"error": "Order cannot be cancelled. It may already be ready or delivered."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            with transaction.atomic():
                for order in customer_order.orders.all():
                    order.status = 'CANCELLED'
                    order.save()
                    
                    OrderStatusLog.objects.create(
                        order=order,
                        status='CANCELLED',
                        note="Cancelled by customer"
                    )
            
            return Response({"message": "Order cancelled successfully."}, status=status.HTTP_200_OK)

        except CustomerOrder.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

class CustomerOrderListView(generics.ListAPIView):
    serializer_class = CustomerOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == 'ADMIN':
            return CustomerOrder.objects.all()
        return CustomerOrder.objects.filter(customer=self.request.user)

class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Order.objects.all()
        if user.role == 'PRODUCER':
            return Order.objects.filter(producer=user).distinct()
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
SERVICE_SECRET_KEY    = os.environ.get('NOTIFICATIONS_API_SECRET_KEY') or os.environ.get('JWT_SECRET_KEY', 'change-this-secret')

class OrderStatusUpdateView(APIView):
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

        order.status = new_status
        order.save()

        from .models import OrderStatusLog
        OrderStatusLog.objects.create(
            order=order,
            producer=request.user,
            status=new_status,
            note=note
        )

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
                    'email':   order.customer.email,
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
            pass

        return Response({'success': True, 'status': new_status})

class ReorderView(APIView):
    permission_classes = [IsCustomerOrCommunityRepresentative]

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

                if not product.is_available or product.stock_quantity < 1 or not is_in_season(product):
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
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def post(self, request):
        customer_order_id = request.data.get('customer_order_id')

        order_day = request.data.get('order_day')
        delivery_day = request.data.get('delivery_day')

        collection_types = request.data.get('collection_types', {})

        if order_day is None or delivery_day is None:
            return Response({'error': 'order_day and delivery_day are required.'}, status=400)

        days_between = (int(delivery_day) - int(order_day)) % 7
        if days_between == 0:
            days_between = 7
        if days_between < 2:
            return Response({
                'error': 'Delivery day must be at least 2 days after order day.'
            }, status=400)

        try:
            customer_order = CustomerOrder.objects.get(pk=customer_order_id, customer=request.user)
        except CustomerOrder.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        today = timezone.now().date()
        days_ahead = (int(order_day) - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_order_date = today + datetime.timedelta(days=days_ahead)

        recurring_order = RecurringOrder.objects.create(
            customer=request.user,
            source_customer_order=customer_order,
            order_day=order_day,
            delivery_day=delivery_day,
            collection_types=collection_types,
            next_order_date=next_order_date,
        )

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
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def get(self, request):
        recurring_orders = RecurringOrder.objects.filter(
            customer=request.user
        ).prefetch_related('items__product')
        serializer = RecurringOrderSerializer(recurring_orders, many=True)
        return Response(serializer.data)

class RecurringOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCustomerOrCommunityRepresentative]
    serializer_class = RecurringOrderSerializer

    def get_queryset(self):
        return RecurringOrder.objects.filter(
            customer=self.request.user
        ).prefetch_related('items__product')

class RecurringOrderUpdateView(APIView):
    permission_classes = [IsCustomerOrCommunityRepresentative]

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

class UpdateRecurringOrdersDate(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.role != 'ADMIN':
            return Response({'error': 'Admin only.'}, status=403)

        RecurringOrder.objects.filter(
            status=RecurringOrder.Status.ACTIVE
        ).update(next_order_date=timezone.now().date())

        return Response({'success': True})


class TriggerRecurringOrdersView(APIView):
    """
    Triggers the cron job command for processing recurring orders.
    This can be done from the admin dashboard only.

    - For demonstration purposes only -
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.role != 'ADMIN':
            return Response({'error': 'Admin only.'}, status=403)

        out = StringIO()
        call_command('process_recurring_orders', stdout=out)
        output = out.getvalue()

        return Response({'success': True, 'output': output})
