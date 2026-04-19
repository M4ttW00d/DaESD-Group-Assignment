from django.urls import path
from .views import (
    OrderListView, OrderDetailView, OrderStatusUpdateView,
    OrderCreateView, CustomerOrderListView, CustomerOrderDetailView,
    ReorderView, RecurringOrderCreateView, RecurringOrderListView,
    RecurringOrderDetailView, RecurringOrderUpdateView)

urlpatterns = [
    path('', OrderListView.as_view(), name='order-list'),
    path('<int:pk>/', OrderDetailView.as_view(), name='order-detail'),
    path('<int:pk>/status/', OrderStatusUpdateView.as_view(), name='order-status-update'),
    path('place/', OrderCreateView.as_view(), name='checkout'),
    path('customer-orders/', CustomerOrderListView.as_view(), name='customer-order-list'),
    path('customer-orders/<int:pk>/', CustomerOrderDetailView.as_view(), name='customer-order-detail'),
    path('<int:pk>/reorder/', ReorderView.as_view(), name='order-reorder'),
    path('recurring/', RecurringOrderCreateView.as_view()),
    path('recurring/list/', RecurringOrderListView.as_view()),
    path('recurring/<int:pk>/', RecurringOrderDetailView.as_view()),
    path('recurring/<int:pk>/update/', RecurringOrderUpdateView.as_view()),
]
