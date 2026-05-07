from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count
from .models import Review

@receiver(post_save, sender=Review)
@receiver(post_delete, sender=Review)
def update_product_average_rating(sender, instance, **kwargs):
    product = instance.product
    
    # Calculate the new average rating and count
    aggregates = Review.objects.filter(product=product).aggregate(
        avg_rating=Avg('rating'),
        count=Count('id')
    )
    
    # If there are no reviews, Avg returns None. Default to 0.00
    product.average_rating = aggregates['avg_rating'] or 0.00
    product.review_count = aggregates['count'] or 0
    product.save(update_fields=['average_rating', 'review_count'])