from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError

def validate_product_image(image):
    # Max file size: 2MB
    filesize = image.size
    if filesize > 2 * 1024 * 1024:
        raise ValidationError(_("Maximum file size is 2MB"))

    # Reasonable dimensions (Max 2000x2000)
    width = image.width
    height = image.height
    if width > 2000 or height > 2000:
        raise ValidationError(_("Image dimensions should not exceed 2000x2000 pixels"))
    
    # Optional: Minimum dimensions for quality
    if width < 100 or height < 100:
        raise ValidationError(_("Image dimensions should be at least 100x100 pixels"))

class Category(models.Model):
    """
    Grouping for products (e.g., Vegetables, Dairy).
    """
    name = models.CharField(max_length=100, unique=True, help_text=_("Vegetables, Dairy, Bakery, etc."))

    class Meta:
        db_table = 'categories'
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

class Product(models.Model):
    """
    Represents a food item offered by a producer.
    """
    # Removed internal Category enum, using ForeignKey to Category model
    
    producer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name="products")
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, blank=True, null=True, help_text=_("e.g., 'dozen', 'kg'"))
    
    stock_quantity = models.PositiveIntegerField(default=0, help_text=_("Real-time inventory tracking"))
    low_stock_threshold = models.PositiveIntegerField(
        default=10,
        help_text=_("Send a LOW_STOCK notification to the producer when stock falls to or below this value")
    )
    allergen_info = models.TextField(blank=True, null=True, help_text=_("Additional allergen information not covered by the 14 major allergens"))
    allergens = models.JSONField(default=list, blank=True, help_text=_("List of major allergens from the UK 14 allergens list"))
    
    is_organic = models.BooleanField(default=False, help_text=_("Supports customer quality filters"))
    is_available = models.BooleanField(default=True)
    
    harvest_date = models.DateField(blank=True, null=True)
    best_before_date = models.DateField(blank=True, null=True, help_text=_("Required for customer transparency"))
    
    seasonal_start_month = models.PositiveSmallIntegerField(blank=True, null=True, help_text=_("Automation for seasonal visibility (1-12)"))
    seasonal_end_month = models.PositiveSmallIntegerField(blank=True, null=True, help_text=_("Automation for seasonal visibility (1-12)"))
    
    image = models.ImageField(
        upload_to="products/", 
        blank=True, 
        null=True,
        validators=[validate_product_image]
    )
    
    seasonal_reminder_sent_month = models.PositiveSmallIntegerField(
        blank=True, null=True,
        help_text=_("Month (1-12) for which the last seasonal reminder was sent, to avoid duplicates")
    )
    seasonal_reminder_sent_year = models.PositiveSmallIntegerField(
        blank=True, null=True,
        help_text=_("Year for which the last seasonal reminder was sent, to avoid duplicates")
    )

    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00, help_text=_("Cached average rating"))
    review_count = models.PositiveIntegerField(default=0, help_text=_("Number of reviews"))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'

    @property
    def is_currently_in_season(self):
        """
        Dynamically determine if the product is in season based on current month.
        If no season is specified, it is always considered in season.
        """
        if not self.seasonal_start_month or not self.seasonal_end_month:
            return True
        current_month = timezone.now().month
        if self.seasonal_start_month <= self.seasonal_end_month:
            return self.seasonal_start_month <= current_month <= self.seasonal_end_month
        else:
            # Handles cases like Nov to Feb (11 to 2)
            return current_month >= self.seasonal_start_month or current_month <= self.seasonal_end_month

    @property
    def seasonal_availability_text(self):
        """Returns formatted string like 'Jun - Aug'."""
        if not self.seasonal_start_month or not self.seasonal_end_month:
            return None
        months = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun', 
                  7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}
        return f"{months.get(self.seasonal_start_month)} - {months.get(self.seasonal_end_month)}"

    @property
    def surplus_deal(self):
        """Returns the active surplus deal if one exists."""
        now = timezone.now()
        # Find a deal that hasn't expired yet
        # Evaluate in memory so prefetch_related works efficiently
        deals = [d for d in self.surplus_deals.all() if d.expiry_date > now]
        if deals:
            # return the deal with the highest discount
            return max(deals, key=lambda d: d.discount_percentage)
        return None

    @property
    def is_surplus(self):
        """Returns True if there is an active surplus deal."""
        return self.surplus_deal is not None

    @property
    def current_price(self):
        """Calculates the current price, applying any active surplus discount."""
        deal = self.surplus_deal
        if deal:
            discount_multiplier = Decimal('1') - (deal.discount_percentage / Decimal('100'))
            return (self.price * discount_multiplier).quantize(Decimal('0.01'))
        return self.price

    def __str__(self):
        return f"{self.name} - {self.producer.username}"

class Recipe(models.Model):
    """
    Educational content: Recipes sharing how to use products.
    """
    producer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recipes")
    products = models.ManyToManyField(Product, related_name="recipes", blank=True)
    
    title = models.CharField(max_length=255)
    description = models.TextField(help_text=_("Brief overview of the recipe"))
    ingredients = models.TextField(help_text=_("List of ingredients"))
    instructions = models.TextField(help_text=_("Step-by-step cooking instructions"))
    season_tag = models.CharField(max_length=100, blank=True, null=True, help_text=_("e.g. Autumn/Winter"))
    image = models.ImageField(upload_to="recipes/", blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'recipes'
        unique_together = ('producer', 'title')

    def __str__(self):
        return f"{self.title} by {self.producer.username}"

class FarmStory(models.Model):
    """
    Educational content: Stories from the farm to engage the community.
    """
    producer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="farm_stories")
    
    title = models.CharField(max_length=255)
    content = models.TextField(help_text=_("The story content"))
    image = models.ImageField(upload_to="farm_stories/", blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'farm_stories'
        unique_together = ('producer', 'title')

    def __str__(self):
        return f"{self.title} by {self.producer.username}"
