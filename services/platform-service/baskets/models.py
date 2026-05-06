from django.db import models
from django.conf import settings
from products.models import Product

class Basket(models.Model):
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='basket'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'baskets'

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())
    
    @property
    def total_price(self):
        return sum(item.product.current_price * item.quantity for item in self.items.all())

    def __str__(self):
        return f"Basket of customer {self.customer_id}"


class BasketItem(models.Model):
    basket = models.ForeignKey(Basket, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='basket_items')
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)
    reserved_at = models.DateTimeField(auto_now=True)  # refreshes on every save

    class Meta:
        db_table = 'basket_items'
        unique_together = ('basket', 'product')

    @property
    def subtotal(self):
        return self.product.current_price * self.quantity

    def __str__(self):
        return f"Item {self.product_id} x {self.quantity} in basket {self.basket.id}"