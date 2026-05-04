from django.contrib import admin
from django.urls import path
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage
from web import views

handler404 = views.custom_404

urlpatterns = [
    # Favicon
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('web/assets/favicon.ico'), permanent=True)),

    # Index
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    
    # Products listing and catalogue
    path('products/new/', views.add_product_view, name='add_product'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),
    path('products/<int:product_id>/edit/', views.edit_product_view, name='edit_product'),
    path('products/<int:product_id>/delete/', views.delete_product_view, name='delete_product'),
    
    # Producer dashboard
    path('dashboard/', views.producer_dashboard, name='dashboard'),
    
    # Login & registration
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Customer basket and checkout
    path('basket/', views.basket_view, name='basket'),
    path('basket/add/<int:product_id>/', views.add_to_basket, name='add-to-basket'),
    path('basket/update/<int:item_id>/', views.update_basket_item, name='update-basket-item'),
    path('basket/remove/<int:item_id>/', views.remove_from_basket, name='remove-from-basket'),
    path('basket/clear/', views.clear_basket, name='clear-basket'),
    path('basket/checkout/', views.checkout_view, name='checkout'),
    
    # Orders placement
    path('orders/', views.customer_order_history_view, name='customer-orders'),
    path('orders/place/', views.create_order, name='create-order'),
    path('orders/customer/<int:order_id>/', views.customer_order_detail_view, name='customer-order-detail'),
    path('reviews/create/<int:product_id>/', views.write_review_view, name='write_review'),
    path('reviews/<int:review_id>/delete/', views.delete_review_view, name='delete_review'),

    # Profile, admin and producer
    path('profile/', views.profile_view, name='profile'),
    path('admin-dashboard/', views.admin_dashboard, name='admin-dashboard'),
    path('admin-dashboard/commission/export/', views.admin_commission_export, name='admin-commission-export'),
    path('admin-dashboard/users/<int:user_id>/delete/', views.admin_delete_user, name='admin-delete-user'),
    path('admin-dashboard/users/<int:user_id>/edit/', views.admin_edit_user, name='admin-edit-user'),
    path('admin-dashboard/products/<int:product_id>/delete/', views.admin_delete_product, name='admin-delete-product'),
    path('dashboard/orders/', views.producer_orders_view, name='producer_orders'),
    path('dashboard/orders/<int:order_id>/', views.producer_order_detail_view, name='producer_order_detail'),
    path('dashboard/orders/<int:order_id>/status/', views.producer_update_order_status_view, name='producer_update_order_status'),
    path('dashboard/content/', views.producer_content_dashboard, name='producer_content_dashboard'),
    path('dashboard/content/recipes/add/', views.add_recipe_view, name='add_recipe'),
    path('dashboard/content/recipes/<int:recipe_id>/delete/', views.delete_recipe_view, name='delete_recipe'),
    path('dashboard/content/stories/add/', views.add_farm_story_view, name='add_farm_story'),
    path('dashboard/content/stories/<int:story_id>/delete/', views.delete_farm_story_view, name='delete_farm_story'),
    
    # Public Producer Profile
    path('producers/<int:producer_id>/', views.producer_public_profile, name='producer_public_profile'),

    # Notifications proxy
    path('notifications/count/', views.notifications_count_view, name='notifications-count'),
    path('notifications/', views.notifications_list_view, name='notifications-list'),
    path('notifications/<int:pk>/read/', views.notifications_mark_read_view, name='notifications-mark-read'),
    path('notifications/read-all/', views.notifications_mark_all_read_view, name='notifications-mark-all-read'),

    path('producers/<int:producer_id>/favourite/', views.favourite_toggle_view, name='favourite-toggle'),
    path('favourites/', views.favourite_list_view, name='favourite-list'),
]
