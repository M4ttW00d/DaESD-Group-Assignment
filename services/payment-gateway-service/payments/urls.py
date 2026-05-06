from django.urls import path

from . import views

app_name = 'payments'

urlpatterns = [
    path('success/', views.checkout_success, name='success'),
    path('cancel/', views.checkout_cancel, name='cancel'),
    path('webhook/', views.webhook, name='webhook'),
    path('api/checkout/', views.create_checkout, name='api-checkout'),
    path('api/payment-status/', views.payment_status, name='api-payment-status'),
    path('api/transactions/', views.list_transactions, name='api-transactions'),
    path('api/payment-order-reference/', views.update_payment_order_reference, name='api-payment-order-reference'),
    path('api/unsettled/', views.list_unsettled_payments, name='api-unsettled'),
    path('api/settlements/', views.list_settlements, name='api-settlements'),
    path('api/settlements/run/', views.run_settlement, name='api-settlements-run'),
    path('api/refund/', views.refund_by_order, name='api-refund'),
    path('api/webhook/', views.webhook, name='api-webhook'),
]
