from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    UserRegistrationView, UserDetailView, UserListView,
    UserAdminDetailView, ProducerPublicDetailView, ProducerPublicProfileView,
    FavouriteProducerView
)

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', UserDetailView.as_view(), name='user_detail'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/<int:pk>/', UserAdminDetailView.as_view(), name='user_admin_detail'),
    path('public-producers/<int:pk>/', ProducerPublicDetailView.as_view(), name='producer_public_detail'),
    path('public-producers/<int:pk>/profile/', ProducerPublicProfileView.as_view(), name='producer_public_profile'),
    path('favourites/', FavouriteProducerView.as_view(), name='favourite-list'),
    path('favourites/<int:producer_id>/', FavouriteProducerView.as_view(), name='favourite-toggle'),
]
