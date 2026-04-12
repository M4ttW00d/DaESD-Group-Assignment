from rest_framework import serializers
from .models import Order, OrderItem, OrderStatusLog, CustomerOrder
from products.models import Product
from decimal import Decimal

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    
    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_name', 'quantity', 'price_at_sale')
        read_only_fields = ('id', 'price_at_sale')

class OrderStatusLogSerializer(serializers.ModelSerializer):
    producer_name = serializers.ReadOnlyField(source='producer.username')

    class Meta:
        model = OrderStatusLog
        fields = ('id', 'producer', 'producer_name', 'status', 'note', 'created_at')
        read_only_fields = ('id', 'producer', 'producer_name', 'created_at')

class OrderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    status_logs = OrderStatusLogSerializer(many=True, read_only=True)
    customer_username = serializers.ReadOnlyField(source='customer.username')
    customer_postcode = serializers.CharField(source='customer.customer_profile.postcode', read_only=True, default='')
    
    # Customer Details for Producers
    customer_first_name = serializers.CharField(source='customer.customer_profile.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.customer_profile.last_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    delivery_address = serializers.CharField(source='customer.customer_profile.delivery_address', read_only=True)
    
    # Producer Details
    producer_name = serializers.CharField(source='producer.producer_profile.business_name', read_only=True)
    
    # Producer specific total
    producer_total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            'id', 'customer', 'customer_username', 'customer_postcode', 'customer_first_name', 'customer_last_name',
            'customer_phone', 'customer_email', 'delivery_address', 'collection_type',
            'total_amount', 'commission_total', 'producer_name', 'producer_total',
            'status', 'status_logs', 'delivery_date', 'created_at', 'items'
        )
        read_only_fields = ('id', 'customer', 'total_amount', 'commission_total', 'created_at', 'items', 'producer_total', 'status_logs')

    def get_items(self, obj):
        request = self.context.get('request')
        items = obj.items.all()
        
        if request and hasattr(request, 'user') and request.user.role == 'PRODUCER':
            items = items.filter(product__producer=request.user)
            
        return OrderItemSerializer(items, many=True).data

    def get_producer_total(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.role == 'PRODUCER':
            items = obj.items.filter(product__producer=request.user)
            return sum(item.price_at_sale * item.quantity for item in items)
        return None

class CustomerOrderSerializer(serializers.ModelSerializer):
    orders = OrderSerializer(many=True, read_only=True)
    overall_status = serializers.CharField(read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = CustomerOrder
        fields = (
            'id', 'customer', 'total_amount', 'commission_total', 'overall_status',
            'total_items', 'orders', 'created_at', 'updated_at'
        )
