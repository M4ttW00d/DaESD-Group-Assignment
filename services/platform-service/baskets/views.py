from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Basket, BasketItem
from .serializers import BasketSerializer
from products.models import Product


class IsCustomerOrCommunityRepresentative(permissions.BasePermission):
    """
    Custom permission to only allow Customers to add product items to their basket.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'CUSTOMER' or request.user.role == 'COMMUNITY-GROUP-REPRESENTATIVE'
    
class CheckoutView(generics.RetrieveAPIView):
    """
    Get the authenticated customer's basket.
    """
    serializer_class = BasketSerializer
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def get_object(self):
        basket= Basket.objects.get(customer=self.request.user)
        return basket

class BasketView(generics.RetrieveAPIView):
    """
    Get the authenticated customer's basket.
    Creates basket if it doesn't exist.
    """
    serializer_class = BasketSerializer
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def get_object(self):
        basket, created = Basket.objects.get_or_create(customer=self.request.user)
        return basket

    
class AddToBasketView(APIView):
    """
    Add a product to the customer's basket or update quantity if already exists.
    """
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def post(self, request):
        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity', 1)

        if not product_id:
            return Response({'error': 'product_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quantity = int(quantity)
            if quantity < 1:
                return Response({'error': 'Quantity must be at least 1'}, status=status.HTTP_400_BAD_REQUEST)
            elif quantity > 10 and request.user.role == "CUSTOMER":
                return Response({'error': 'Only a maximum of 10 items are allowed per product. If you would like to place bulk orders, please register as a community group representative.'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid quantity'}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, id=product_id, is_available=True)
        
        if product.stock_quantity < quantity:
            return Response(
                {'error': f'Only {product.stock_quantity} units available in stock'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        basket, created = Basket.objects.get_or_create(customer=request.user)
        
        basket_item, item_created = BasketItem.objects.get_or_create(
            basket=basket,
            product=product,
            defaults={'quantity': quantity}
        )
        
        if not item_created:
            
            # Item already in basket, update quantity
            new_quantity = basket_item.quantity + quantity
            remaining_stock = product.stock_quantity - basket_item.quantity
            
            if remaining_stock <= 0:
                return Response(
                    {'error': f'You already have {basket_item.quantity} of this item in your basket (maximum available)'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if new_quantity > product.stock_quantity:
                return Response(
                    {'error': f'You already have {basket_item.quantity} in your basket. Only {remaining_stock} more available'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            basket_item.quantity = new_quantity
            basket_item.save()

        serializer = BasketSerializer(basket)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class UpdateBasketItemView(APIView):
    """
    Update quantity of a specific basket item.
    """
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def patch(self, request, item_id):
        basket = get_object_or_404(Basket, customer=request.user)
        basket_item = get_object_or_404(BasketItem, id=item_id, basket=basket)
        
        quantity = request.data.get('quantity')
        if quantity is None:
            return Response({'error': 'quantity is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quantity = int(quantity)
            if quantity < 1:
                return Response({'error': 'Quantity must be at least 1'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid quantity'}, status=status.HTTP_400_BAD_REQUEST)

        if quantity > basket_item.product.stock_quantity:
            return Response(
                {'error': f'There are only {basket_item.product.stock_quantity} units available in stock for this product'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        basket_item.quantity = quantity
        basket_item.save()

        serializer = BasketSerializer(basket)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RemoveFromBasketView(APIView):
    """
    Remove an item from the basket.
    """
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def delete(self, request, item_id):
        basket = get_object_or_404(Basket, customer=request.user)
        basket_item = get_object_or_404(BasketItem, id=item_id, basket=basket)
        basket_item.delete()

        serializer = BasketSerializer(basket)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ClearBasketView(APIView):
    """
    Remove all items from the basket.
    """
    permission_classes = [IsCustomerOrCommunityRepresentative]

    def delete(self, request):
        basket = get_object_or_404(Basket, customer=request.user)
        basket.items.all().delete()
        
        serializer = BasketSerializer(basket)
        return Response(serializer.data, status=status.HTTP_200_OK)