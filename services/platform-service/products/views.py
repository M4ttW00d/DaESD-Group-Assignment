import os
import requests as http_requests

from rest_framework import generics, permissions, filters, status
from rest_framework.response import Response
from django.db.models import Q, F
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product, Category, Recipe, FarmStory
from .serializers import ProductSerializer, CategorySerializer, RecipeSerializer, FarmStorySerializer

NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')
SERVICE_SECRET_KEY    = os.environ.get('JWT_SECRET_KEY', 'change-this-secret-key-for-jwt-tokens')

class IsProducerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow Producers to edit or create products.
    Admins can delete any product.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not request.user.is_authenticated:
            return False
        return request.user.role in ('PRODUCER', 'ADMIN')

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        # Admins can edit or delete any product
        if request.user.role == 'ADMIN':
            return True
        # Producers can only edit/delete their own products
        return obj.producer == request.user

class CategoryList(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly] # Allow admins to create? For now open or just producers? Let's generic.

class ProductListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsProducerOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category__name', 'is_organic', 'producer__username', 'is_available']
    search_fields = ['name', 'description', 'producer__username']
    ordering_fields = ['price', 'created_at', 'stock_quantity']

    def get_queryset(self):
        queryset = Product.objects.all()
        # Filter out products containing specified allergens
        exclude_allergens = self.request.query_params.getlist('exclude_allergen')
        if exclude_allergens:
            for allergen in exclude_allergens:
                # Exclude products whose allergens JSON list contains this allergen
                queryset = queryset.exclude(allergens__contains=allergen)
                
        user = self.request.user
        
        # We no longer filter out-of-season products at the database level.
        # They should be visible on the frontend but marked as 'Out of Season'
        # and unpurchasable.
            
        return queryset

    def perform_create(self, serializer):
        serializer.save(producer=self.request.user)

class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsProducerOrReadOnly]

    def perform_update(self, serializer):
        from orders.models import SurplusDeal, Order

        product = self.get_object()

        was_surplus = SurplusDeal.objects.filter(
            product=product, expiry_date__gt=timezone.now()
        ).exists()

        updated_product = serializer.save()

        now_surplus = SurplusDeal.objects.filter(
            product=updated_product, expiry_date__gt=timezone.now()
        ).exists()

        if now_surplus and not was_surplus:
            deal = (
                SurplusDeal.objects
                .filter(product=updated_product, expiry_date__gt=timezone.now())
                .order_by('-id')
                .first()
            )
            discount = deal.discount_percentage if deal else ''

            prior_customer_ids = set(
                Order.objects
                .filter(producer=updated_product.producer)
                .values_list('customer_id', flat=True)
                .distinct()
            )

            from users.models import FavouriteProducer
            favouriter_ids = set(
                FavouriteProducer.objects
                .filter(producer=updated_product.producer)
                .values_list('customer_id', flat=True)
                .distinct()
            )

            all_customer_ids = prior_customer_ids | favouriter_ids

            for customer_id in all_customer_ids:
                try:
                    http_requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/",
                        json={
                            'user':    customer_id,
                            'message': (
                                f"Surplus deal: '{updated_product.name}' is now {discount}% off. "
                                "Limited time offer — grab it before it's gone!"
                            ),
                            'type':  'SURPLUS_DEAL',
                            'title': f"Surplus Deal: {updated_product.name}",
                        },
                        headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                        timeout=5
                    )
                except Exception:
                    pass

        if updated_product.seasonal_start_month:
            now = timezone.now()
            next_month = now.month % 12 + 1
            current_year = now.year

            already_sent = (
                updated_product.seasonal_reminder_sent_month == next_month
                and updated_product.seasonal_reminder_sent_year == current_year
            )

            if updated_product.seasonal_start_month == next_month and not already_sent:
                months = {
                    1: 'January', 2: 'February', 3: 'March', 4: 'April',
                    5: 'May', 6: 'June', 7: 'July', 8: 'August',
                    9: 'September', 10: 'October', 11: 'November', 12: 'December',
                }
                try:
                    http_requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/",
                        json={
                            'user':    updated_product.producer.id,
                            'type':    'SEASONAL_REMINDER',
                            'title':   f"Season Starting: {updated_product.name}",
                            'message': (
                                f"Your product '{updated_product.name}' comes into season in "
                                f"{months[next_month]}. Make sure your stock is ready for customers!"
                            ),
                        },
                        headers={'X-Service-Secret': SERVICE_SECRET_KEY},
                        timeout=5,
                    )
                    Product.objects.filter(pk=updated_product.pk).update(
                        seasonal_reminder_sent_month=next_month,
                        seasonal_reminder_sent_year=current_year,
                    )
                except Exception:
                    pass

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError:
            # Product has order history — mark as unavailable instead of deleting
            instance.is_available = False
            instance.save()
            return Response(
                {'detail': 'Product has existing orders and cannot be deleted. It has been marked as unavailable instead.'},
                status=status.HTTP_200_OK
            )

class CategoryDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

class RecipeListCreateView(generics.ListCreateAPIView):
    queryset = Recipe.objects.all()
    serializer_class = RecipeSerializer
    permission_classes = [IsProducerOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['producer__username', 'products__id']
    search_fields = ['title', 'description', 'ingredients', 'producer__username']
    ordering_fields = ['created_at']

    def perform_create(self, serializer):
        serializer.save(producer=self.request.user)

class RecipeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Recipe.objects.all()
    serializer_class = RecipeSerializer
    permission_classes = [IsProducerOrReadOnly]

class FarmStoryListCreateView(generics.ListCreateAPIView):
    queryset = FarmStory.objects.all()
    serializer_class = FarmStorySerializer
    permission_classes = [IsProducerOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['producer__username']
    search_fields = ['title', 'content', 'producer__username']
    ordering_fields = ['created_at']

    def perform_create(self, serializer):
        serializer.save(producer=self.request.user)

class FarmStoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FarmStory.objects.all()
    serializer_class = FarmStorySerializer
    permission_classes = [IsProducerOrReadOnly]
