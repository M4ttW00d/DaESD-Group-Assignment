from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ProducerProfile, CustomerProfile, CommunityGroupProfile
import re

User = get_user_model()

UK_POSTCODE_RE = re.compile(
    r'^[A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2}$',
    re.IGNORECASE
)

def validate_uk_postcode(value):
    if not value or not value.strip():
        return value
    # Remove all spaces and uppercase
    cleaned = value.strip().replace(' ', '').upper()
    # UK postcode format: insert space before last 3 chars
    if len(cleaned) >= 5:
        formatted = cleaned[:-3] + ' ' + cleaned[-3:]
    else:
        formatted = cleaned
    # Validate format
    if not UK_POSTCODE_RE.match(formatted):
        raise serializers.ValidationError("Enter a valid UK postcode (e.g. BS1 1AA).")
    return formatted

class ProducerProfileSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(required=False, allow_blank=True, default='')
    business_address = serializers.CharField(required=False, allow_blank=True, default='')
    postcode = serializers.CharField(required=False, allow_blank=True, default='')
    bio = serializers.CharField(required=False, allow_blank=True, default='')
    stripe_account_id = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = ProducerProfile
        fields = ('business_name', 'business_address', 'postcode', 'bio', 'stripe_account_id')

    def validate_postcode(self, value):
        if value and value.strip():
            return validate_uk_postcode(value)
        return value

class CustomerProfileSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(required=False, allow_blank=True, default='')
    last_name = serializers.CharField(required=False, allow_blank=True, default='')
    delivery_address = serializers.CharField(required=False, allow_blank=True, default='')
    postcode = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = CustomerProfile
        fields = ('first_name', 'last_name', 'delivery_address', 'postcode')

    def validate_postcode(self, value):
        if value and value.strip():
            return validate_uk_postcode(value)
        return value
    
class CommunityGroupProfileSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(required=False, allow_blank=True, default='')
    organization_type = serializers.CharField(required=False, allow_blank=True, default='')
    delivery_address = serializers.CharField(required=False, allow_blank=True, default='')
    postcode = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = CommunityGroupProfile
        fields = ('organization_name', 'organization_type', 'delivery_address', 'postcode')

    def validate_postcode(self, value):
        if value and value.strip():
            return validate_uk_postcode(value)
        return value

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    producer_profile = ProducerProfileSerializer(required=False)
    customer_profile = CustomerProfileSerializer(required=False)
    community_profile = CommunityGroupProfileSerializer(required=False)

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'email', 'role', 'phone_number', 'producer_profile', 'customer_profile', 'community_profile')
        read_only_fields = ('id',)

    def create(self, validated_data):
        producer_data = validated_data.pop('producer_profile', None)
        customer_data = validated_data.pop('customer_profile', None)
        community_group_data = validated_data.pop('community_profile', None)

        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            role=validated_data.get('role', 'CUSTOMER'),
            phone_number=validated_data.get('phone_number', ''),
        )

        if user.role == 'PRODUCER':
            ProducerProfile.objects.create(user=user, **(producer_data or {}))
        elif user.role == 'CUSTOMER':
            CustomerProfile.objects.create(user=user, **(customer_data or {}))
        elif user.role == 'COMMUNITY-GROUP-REPRESENTATIVE':
            CommunityGroupProfile.objects.create(user=user, **(community_group_data or {}))

        return user

    def update(self, instance, validated_data):
        producer_data = validated_data.pop('producer_profile', None)
        customer_data = validated_data.pop('customer_profile', None)
        community_group_data = validated_data.pop('community_profile', None)
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if producer_data and instance.role == 'PRODUCER':
            ProducerProfile.objects.update_or_create(user=instance, defaults=producer_data)
        if customer_data and instance.role == 'CUSTOMER':
            CustomerProfile.objects.update_or_create(user=instance, defaults=customer_data)
        if community_group_data and instance.role == 'COMMUNITY-GROUP-REPRESENTATIVE':
            CommunityGroupProfile.objects.update_or_create(user=instance, defaults=community_group_data)

        return instance

class ProducerPublicSerializer(serializers.ModelSerializer):
    producer_profile = ProducerProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'producer_profile')
        read_only_fields = ('id', 'username', 'producer_profile')
