from django.db import models
from django.conf import settings
from products.models import Product
from orders.models import Order
from django.core.validators import MinValueValidator, MaxValueValidator

class Review(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True) # Optional link to verified purchase
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], help_text="1-5 Star scale")
    title = models.CharField(max_length=255, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    seller_response = models.TextField(blank=True, null=True, help_text="Producer's response to the review")
    is_anonymous = models.BooleanField(default=False, help_text="Hide customer name from public")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reviews'
        unique_together = ('customer', 'product')

    def __str__(self):
        return f"{self.rating}/5 for {self.product.name} by {self.customer.username}"
