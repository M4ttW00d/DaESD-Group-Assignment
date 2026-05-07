from rest_framework import serializers
from .models import Review
from orders.models import OrderItem

class ReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.SerializerMethodField()
    product_name = serializers.ReadOnlyField(source='product.name')

    class Meta:
        model = Review
        fields = ('id', 'customer', 'customer_username', 'product', 'product_name', 'order', 'rating', 'title', 'comment', 'seller_response', 'is_anonymous', 'created_at')
        read_only_fields = ('id', 'customer', 'order', 'seller_response', 'created_at')

    def get_customer_username(self, obj):
        if obj.is_anonymous:
            return "Anonymous Customer"
        return obj.customer.username

    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user:
            return data

        product = data.get('product')
        customer = request.user
        comment = data.get('comment', '')
        title = data.get('title', '') or ''

        import re
        # Expletive filter - Top 10 common swear words (using regex for whole-word matching)
        # Can expand list further or use a more comprehensive profanity filter library if needed
        banned_words = [
            'fuck', 'shit', 'asshole', 'bitch', 'cunt', 
            'dick', 'piss', 'bastard', 'slut', 'whore'
        ]
        content_to_check = (title + ' ' + comment).lower()
        
        # Check if the customer has a DELIVERED order for this product
        delivered_item = OrderItem.objects.filter(
            order__customer=customer,
            order__status='DELIVERED',
            product=product
        ).first()

        if not delivered_item:
            raise serializers.ValidationError("You can only review products from orders that have been DELIVERED.")

        # Check if the customer has already reviewed this product
        if Review.objects.filter(customer=customer, product=product).exists():
            raise serializers.ValidationError("You have already reviewed this product.")

        import re
        for word in banned_words:
            if re.search(rf'\b{word}\b', content_to_check):
                raise serializers.ValidationError("Your review contains inappropriate language. Please keep it professional.")

        # Assign the confirmed delivered order to the review data automatically
        data['order'] = delivered_item.order

        return data
