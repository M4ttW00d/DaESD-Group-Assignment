from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Product, Category, Recipe, FarmStory
from orders.models import SurplusDeal
from django.utils import timezone
from users.serializers import ProducerProfileSerializer
import datetime

class SurplusDealSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurplusDeal
        fields = ('id', 'discount_percentage', 'expiry_date', 'deal_note')

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    producer_username = serializers.ReadOnlyField(source='producer.username')
    producer_profile = ProducerProfileSerializer(source='producer.producer_profile', read_only=True)

    category = serializers.SlugRelatedField(
        slug_field='name', 
        queryset=Category.objects.all(),
        help_text="Name of the category (e.g., 'Vegetables', 'Dairy')"
    )

    is_surplus = serializers.ReadOnlyField()
    current_price = serializers.ReadOnlyField()
    surplus_deal = SurplusDealSerializer(required=False, allow_null=True)
    is_currently_in_season = serializers.ReadOnlyField()
    seasonal_availability_text = serializers.ReadOnlyField()
    image = serializers.ImageField(use_url=False, required=False, allow_null=True)

    class Meta:
        model = Product
        fields = (
            'id', 'producer', 'producer_username', 'producer_profile', 'category', 'name', 'description', 
            'price', 'current_price', 'is_surplus', 'surplus_deal', 'unit', 'stock_quantity', 'low_stock_threshold', 'allergens', 'allergen_info', 'is_organic',
            'is_available', 'harvest_date', 'best_before_date', 
            'seasonal_start_month', 'seasonal_end_month', 'is_currently_in_season',
            'seasonal_availability_text', 'image',
            'average_rating', 'review_count',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'producer', 'created_at', 'updated_at', 'is_surplus', 'current_price', 'is_currently_in_season', 'seasonal_availability_text', 'average_rating', 'review_count')

    def create(self, validated_data):
        surplus_deal_data = validated_data.pop('surplus_deal', None)
        
        request = self.context.get('request')
        if not surplus_deal_data and request and hasattr(request, 'data'):
            has_surplus = str(request.data.get('is_surplus', '')).lower() == 'true'
            if has_surplus:
                surplus_deal_data = {}
                if request.data.get('surplus_deal.discount_percentage'):
                    surplus_deal_data['discount_percentage'] = request.data.get('surplus_deal.discount_percentage')
                if request.data.get('surplus_deal.expiry_date'):
                    surplus_deal_data['expiry_date'] = request.data.get('surplus_deal.expiry_date')
                if request.data.get('surplus_deal.deal_note'):
                    surplus_deal_data['deal_note'] = request.data.get('surplus_deal.deal_note')

        product = super().create(validated_data)
        
        if surplus_deal_data:
            SurplusDeal.objects.create(product=product, **surplus_deal_data)
            
        return product

    def update(self, instance, validated_data):
        surplus_deal_data = validated_data.pop('surplus_deal', None)
        
        request = self.context.get('request')
        if not surplus_deal_data and request and hasattr(request, 'data'):
            has_surplus = str(request.data.get('is_surplus', '')).lower() == 'true'
            if has_surplus:
                surplus_deal_data = {}
                if request.data.get('surplus_deal.discount_percentage'):
                    surplus_deal_data['discount_percentage'] = request.data.get('surplus_deal.discount_percentage')
                if request.data.get('surplus_deal.expiry_date'):
                    surplus_deal_data['expiry_date'] = request.data.get('surplus_deal.expiry_date')
                if request.data.get('surplus_deal.deal_note'):
                    surplus_deal_data['deal_note'] = request.data.get('surplus_deal.deal_note')

        product = super().update(instance, validated_data)
        
        # Determine if we need to update/create/delete the surplus deal
        # The frontend might send an explicit null to clear it, or send data to update it
        if request and 'is_surplus' in request.data:
            is_surplus_str = str(request.data.get('is_surplus')).lower()
            wants_surplus = is_surplus_str == 'true'
            
            if wants_surplus and surplus_deal_data:
                # Update currently active deal or create new
                active_deal = product.surplus_deal
                if active_deal:
                    for attr, value in surplus_deal_data.items():
                        setattr(active_deal, attr, value)
                    active_deal.save()
                else:
                    SurplusDeal.objects.create(product=product, **surplus_deal_data)
            elif not wants_surplus:
                # Delete existing active deal if any
                active_deal = product.surplus_deal
                if active_deal:
                    active_deal.delete()

        return product

class FarmStorySerializer(serializers.ModelSerializer):
    producer_username = serializers.ReadOnlyField(source='producer.username')
    producer_business_name = serializers.ReadOnlyField(source='producer.producer_profile.business_name')
    
    class Meta:
        model = FarmStory
        fields = ('id', 'producer', 'producer_username', 'producer_business_name', 'title', 'content', 'image', 'created_at', 'updated_at')
        read_only_fields = ('id', 'producer', 'created_at', 'updated_at')

class RecipeSerializer(serializers.ModelSerializer):
    producer_username = serializers.ReadOnlyField(source='producer.username')
    producer_business_name = serializers.ReadOnlyField(source='producer.producer_profile.business_name')
    
    class Meta:
        model = Recipe
        fields = ('id', 'producer', 'producer_username', 'producer_business_name', 'products', 'title', 'description', 'ingredients', 'instructions', 'season_tag', 'image', 'created_at', 'updated_at')
        read_only_fields = ('id', 'producer', 'created_at', 'updated_at')
    def validate_products(self, value):
        """
        Check that all products in the recipe belong to the producer.
        """
        request = self.context.get('request')
        if not request or not request.user:
            return value

        # 'value' is a list of Product objects (since it's a many-to-many field)
        invalid_products = [p.name for p in value if p.producer != request.user]
        if invalid_products:
            raise serializers.ValidationError(
                f"The following products do not belong to you: {', '.join(invalid_products)}. "
                "You can only link your own products to recipes."
            )
        return value

User = get_user_model()

class ProducerFullProfileSerializer(serializers.ModelSerializer):
    """
    Composite serializer for the public producer profile page.
    Batches basic info, products, recipes, and farm stories into one response.
    """
    producer_profile = ProducerProfileSerializer(read_only=True)
    products = ProductSerializer(many=True, read_only=True)
    recipes = RecipeSerializer(many=True, read_only=True)
    farm_stories = FarmStorySerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'producer_profile', 'products', 'recipes', 'farm_stories')
        read_only_fields = ('id', 'username', 'producer_profile', 'products', 'recipes', 'farm_stories')
