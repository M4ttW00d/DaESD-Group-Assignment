from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from .models import FavouriteProducer
from .serializers import UserSerializer, ProducerPublicSerializer
from products.serializers import ProducerFullProfileSerializer

User = get_user_model()

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'ADMIN'

class UserRegistrationView(generics.CreateAPIView):
    """
    Handles public user registration.
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = UserSerializer

class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Handles authenticated user profile management.
    """
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        # Always return the current authenticated user
        return self.request.user

class UserListView(generics.ListAPIView):
    """
    Admin-only endpoint to list all users.
    """
    serializer_class = UserSerializer
    permission_classes = (IsAdmin,)

    def get_queryset(self):
        return User.objects.all().order_by('-date_joined')

class UserAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Admin-only endpoint to manage any user.
    """
    serializer_class = UserSerializer
    permission_classes = (IsAdmin,)

    def get_queryset(self):
        return User.objects.all()

class ProducerPublicDetailView(generics.RetrieveAPIView):
    """
    Publicly accessible endpoint to view a producer's business profile.
    """
    serializer_class = ProducerPublicSerializer
    permission_classes = (permissions.AllowAny,)
    
    def get_queryset(self):
        return User.objects.filter(role='PRODUCER')

class ProducerPublicProfileView(generics.RetrieveAPIView):
    """
    Composite endpoint to fetch a producer's full public profile,
    including their products, recipes, and farm stories in one request.
    """
    serializer_class = ProducerFullProfileSerializer
    permission_classes = (permissions.AllowAny,)

    def get_queryset(self):
        return User.objects.filter(role='PRODUCER').prefetch_related(
            'products', 'recipes', 'farm_stories'
        ).select_related('producer_profile')


class FavouriteProducerView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        ids = list(
            FavouriteProducer.objects
            .filter(customer=request.user)
            .values_list('producer_id', flat=True)
        )
        return Response({'favourited_producer_ids': ids})

    def post(self, request, producer_id):
        producer = User.objects.filter(id=producer_id, role='PRODUCER').first()
        if not producer:
            return Response({'detail': 'Producer not found.'}, status=status.HTTP_404_NOT_FOUND)
        if producer == request.user:
            return Response({'detail': 'You cannot favourite yourself.'}, status=status.HTTP_400_BAD_REQUEST)

        fav, created = FavouriteProducer.objects.get_or_create(
            customer=request.user, producer=producer
        )
        if not created:
            fav.delete()
            return Response({'favourited': False})
        return Response({'favourited': True}, status=status.HTTP_201_CREATED)
