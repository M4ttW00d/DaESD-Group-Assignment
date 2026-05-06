import os
import json
import csv
import math
import requests
from datetime import date, timedelta, datetime
from urllib.parse import quote
from django.shortcuts import render, redirect
from django.http import HttpResponse


# Base URL of the platform API service — no trailing slash, no /api suffix
PLATFORM_API_URL = os.environ.get('PLATFORM_API_URL', 'http://platform-api:8002')

# Used by the browser to load product images served by the platform service.
MEDIA_BASE_URL = os.environ.get('MEDIA_BASE_URL', 'http://localhost:8002')
PAYMENT_GATEWAY_URL = os.environ.get('PAYMENT_GATEWAY_URL', 'http://payment-gateway:8003')
PAYMENT_GATEWAY_API_URL = os.environ.get('PAYMENT_GATEWAY_API_URL', PAYMENT_GATEWAY_URL).rstrip('/')
NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')

"""Fetch lat/lng for a UK postcode from postcodes.io. Returns (lat, lng) or (None, None)."""
def _get_postcode_coords(postcode):
    try:
        resp = requests.get(
            f"https://api.postcodes.io/postcodes/{postcode.strip().replace(' ', '%20')}",
            timeout=5
        )
        if resp.status_code == 200:
            result = resp.json().get('result', {})
            if result:
                return result.get('latitude'), result.get('longitude')
    except Exception:
        pass
    return None, None

"""Calculate straight-line distance in miles between two lat/lng points."""
def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

"""Returns distance in miles as a float, or None if postcodes can't be resolved."""
def _calculate_food_miles(customer_postcode, producer_postcode):
    if not customer_postcode or not producer_postcode:
        return None
    lat1, lon1 = _get_postcode_coords(customer_postcode)
    lat2, lon2 = _get_postcode_coords(producer_postcode)
    if None in (lat1, lon1, lat2, lon2):
        return None
    return round(_haversine_miles(lat1, lon1, lat2, lon2), 1)

# UK 14 Major Allergens
UK_ALLERGENS = [
    'Celery', 'Cereals containing gluten', 'Crustaceans', 'Eggs',
    'Fish', 'Lupin', 'Milk', 'Molluscs', 'Mustard', 'Tree nuts',
    'Peanuts', 'Sesame', 'Soya', 'Sulphur dioxide/sulphites',
]

def get_auth_headers(request):
    """Helper method to build authorization headers from session token."""
    token = request.session.get('token')
    if token:
        return {'Authorization': f'Bearer {token}'}
    return {}

def _api_error_message(status_code):
    if status_code == 403:
        return "You do not have permission to access this. Please sign in and try again."
    elif status_code == 404:
        return "The requested resource could not be found."
    elif status_code == 500:
        return "The server encountered an error. Please try again shortly."
    elif status_code == 503:
        return "The service is temporarily unavailable. Please try again in a few moments."
    else:
        return "Something went wrong. Please try again shortly."


AUTH_EXPIRED_ERROR = '__AUTH_EXPIRED__'


def _build_payment_checkout_payload(*, basket, pending_order_reference, customer_email='', customer_id=''):
    """
    Build the JSON payload expected by payment-gateway /payments/api/checkout/
    from the current basket snapshot.
    """
    items = []
    basket_items = basket.get('items') or []
    total_amount = basket.get('total_price')

    for basket_item in basket_items:
        product = basket_item.get('product') or {}
        unit_price = product.get('current_price') or product.get('price')
        if unit_price in (None, ''):
            continue
        items.append({
            'product_name': product.get('name') or f"Product {product.get('id', '')}".strip(),
            'description': product.get('description') or '',
            'quantity': basket_item.get('quantity', 1),
            'price_at_sale': str(unit_price),
        })

    payload = {
        'order_id': pending_order_reference,
        'currency': 'gbp',
        'items': items,
    }

    if not items and total_amount not in (None, ''):
        payload['total_amount'] = str(total_amount)
        payload['title'] = f'Order {pending_order_reference}'

    if customer_email:
        payload['customer_email'] = customer_email

    if customer_id:
        payload['user_id'] = str(customer_id)

    return payload


def _candidate_payment_gateway_api_bases():
    """Return candidate base URLs for payment-gateway API calls."""
    bases = []
    for base in (
        PAYMENT_GATEWAY_API_URL,
        PAYMENT_GATEWAY_URL,
        'http://payment-gateway:8003',
        'http://localhost:8003',
        'http://127.0.0.1:8003',
    ):
        normalized = str(base or '').rstrip('/')
        if normalized and normalized not in bases:
            bases.append(normalized)
    return bases



def _extract_error_from_response(response, default_message):
    try:
        data = response.json()
    except ValueError:
        return default_message
    if isinstance(data, dict):
        return data.get('error') or data.get('detail') or default_message
    return default_message


def _send_payment_notifications(request, order):
    sub_orders     = order.get('orders', [])
    total_amount   = order.get('total_amount', '0.00')
    customer_order_id = order.get('id', '')
    customer_email = sub_orders[0].get('customer_email', '') if sub_orders else ''
    customer_id    = request.session.get('user_id')

    if not customer_id:
        return

    is_bulk = request.session.get('role') == 'COMMUNITY-GROUP-REPRESENTATIVE'
    summary_lines = []
    for sub in sub_orders:
        producer_name = sub.get('producer_name') or 'Producer'
        summary_lines.append(f"\n{producer_name}:")
        for item in sub.get('items', []):
            name  = item.get('product_name', 'Item')
            qty   = item.get('quantity', 1)
            price = item.get('price_at_sale', '0.00')
            summary_lines.append(f"\n  • {name} x{qty} — £{price}")
        collection = sub.get('collection_type', '')
        delivery   = sub.get('delivery_date', '')
        if collection:
            summary_lines.append(f"\n  Collection: {collection}")
        if delivery:
            summary_lines.append(f"\n  Delivery date: {delivery}")
        delivery_instruction = sub.get('delivery_instruction', '')
        if is_bulk and delivery_instruction:
            summary_lines.append(f"\n  Instructions: {delivery_instruction}")
        if is_bulk:
            producer_email = sub.get('producer_email', '')
            producer_phone = sub.get('producer_phone', '')
            if producer_email:
                summary_lines.append(f"\n  Contact: {producer_email}")
            if producer_phone:
                summary_lines.append(f"\n  Phone: {producer_phone}")

    order_summary_message = (
        f"Order #{customer_order_id} — Total: £{total_amount}"
        + "".join(summary_lines)
    )

    secret = os.environ.get('NOTIFICATIONS_API_SECRET_KEY', '')
    headers = {'X-Service-Secret': secret}

    try:
        requests.post(
            f"{NOTIFICATIONS_API_URL}/api/notifications/",
            json={
                'user':    customer_id,
                'email':   customer_email,
                'type':    'PAYMENT_RECEIVED',
                'title':   f'Payment Confirmed — Order #{customer_order_id}',
                'message': f'Your payment of £{total_amount} was successful. Your order #{customer_order_id} has been placed.',
            },
            headers=headers,
            timeout=5,
        )
    except Exception:
        pass

    try:
        requests.post(
            f"{NOTIFICATIONS_API_URL}/api/notifications/",
            json={
                'user':    customer_id,
                'email':   customer_email,
                'type':    'ORDER_SUMMARY',
                'title':   f'Order Summary — #{customer_order_id}',
                'message': order_summary_message,
            },
            headers=headers,
            timeout=5,
        )
    except Exception:
        pass


def _finalize_pending_order(request, *, payment_id, session_id, order_reference):
    pending_checkout = request.session.get('pending_checkout')
    if not isinstance(pending_checkout, dict):
        return None, 'No pending checkout found. Please checkout again.'

    expected_reference = str(pending_checkout.get('order_reference') or '')
    if expected_reference and order_reference and str(order_reference) != expected_reference:
        return None, 'Payment reference mismatch. Please checkout again.'

    finalized_payment_id = str(request.session.get('finalized_payment_id') or '')
    if payment_id and finalized_payment_id == str(payment_id):
        finalized_order_id = request.session.get('finalized_order_id')
        if finalized_order_id:
            return finalized_order_id, None

    if not payment_id or not session_id:
        return None, 'Missing Stripe payment confirmation details.'

    try:
        verify_resp = requests.get(
            f"{PAYMENT_GATEWAY_URL}/payments/api/payment-status/",
            params={'payment_id': payment_id, 'session_id': session_id},
            timeout=10
        )
    except requests.exceptions.ConnectionError:
        return None, 'Cannot reach payment service to verify payment status.'
    except requests.exceptions.Timeout:
        return None, 'Payment verification timed out. Please refresh in a few seconds.'
    except Exception as exc:
        return None, f'Unexpected payment verification error: {str(exc)}'

    if verify_resp.status_code != 200:
        verify_error = _extract_error_from_response(
            verify_resp,
            f'Could not verify payment status (status {verify_resp.status_code}).',
        )
        return None, verify_error

    verify_data = verify_resp.json()
    if verify_data.get('status') != 'SUCCESS':
        return None, 'Payment is not marked as successful yet.'

    try:
        place_resp = requests.post(
            f"{PLATFORM_API_URL}/api/orders/place/",
            headers=get_auth_headers(request),
            json={
                'delivery_dates': pending_checkout.get('delivery_dates', {}),
                'collection_types': pending_checkout.get('collection_types', {}),
                'delivery_instructions': pending_checkout.get('delivery_instructions', {}),
            },
            timeout=10
        )
    except requests.exceptions.ConnectionError:
        return None, 'Cannot reach platform API to place the order.'
    except requests.exceptions.Timeout:
        return None, 'Order placement timed out after payment.'
    except Exception as exc:
        return None, f'Unexpected order placement error: {str(exc)}'

    if place_resp.status_code == 201:
        customer_order_id = place_resp.json().get('id')

        pending_checkout = request.session.get('pending_checkout', {})
        if pending_checkout.get('make_recurring'):
            try:
                requests.post(
                    f"{PLATFORM_API_URL}/api/orders/recurring/",
                    headers=get_auth_headers(request),
                    json={
                        'customer_order_id': customer_order_id,
                        'order_day': pending_checkout.get('order_day'),
                        'delivery_day': pending_checkout.get('delivery_day'),
                        'collection_types': pending_checkout.get('collection_types', {}),
                    },
                    timeout=10
                )
            except Exception:
                pass
        
        request.session['finalized_payment_id'] = str(payment_id)
        request.session['finalized_order_id'] = customer_order_id
        request.session.pop('pending_checkout', None)
        request.session.modified = True
        return customer_order_id, None

    if place_resp.status_code == 401:
        request.session.flush()
        return None, AUTH_EXPIRED_ERROR

    placement_error = _extract_error_from_response(
        place_resp,
        f'Could not place order after payment (status {place_resp.status_code}).',
    )
    return None, placement_error

def trigger_recurring_orders(request):
    if request.method != 'POST':
        return redirect('/admin-dashboard/')
    
    try:
        resp = requests.post(
            f"{PLATFORM_API_URL}/api/orders/recurring/trigger/",
            headers=get_auth_headers(request),
            timeout=15
        )
        if resp.status_code == 200:
            output = resp.json().get('output', '')
            return redirect(f'/admin-dashboard/?success={quote("Recurring orders processed. " + output)}')
        else:
            error = _extract_error_from_response(resp, "Could not trigger recurring orders.")
            return redirect(f'/admin-dashboard/?error={quote(error)}')
    except Exception as e:
        return redirect(f'/admin-dashboard/?error={quote(str(e))}')
    
def update_recurring_orders_reorder_date(request):
    if request.method != 'POST':
        return redirect('/admin-dashboard/')
    
    try:
        resp = requests.post(
            f"{PLATFORM_API_URL}/api/orders/recurring/order-date-update/",
            headers=get_auth_headers(request),
            timeout=15
        )
        if resp.status_code == 200:
            output = resp.json().get('output', '')
            return redirect(f'/admin-dashboard/?success={quote("Active recurring orders reorder date processed. " + output)}')
        else:
            error = _extract_error_from_response(resp, "Could not change recurring orders reorder date.")
            return redirect(f'/admin-dashboard/?error={quote(error)}')
    except Exception as e:
        return redirect(f'/admin-dashboard/?error={quote(str(e))}')

def index(request):
    products = []
    categories = []
    error = None

    search = request.GET.get('search', '').strip()
    selected_category = request.GET.get('category', '').strip()
    is_organic = request.GET.get('organic', '')
    exclude_allergens = request.GET.getlist('exclude_allergen')

    try:
        resp_cat = requests.get(f"{PLATFORM_API_URL}/api/products/categories/", timeout=5)
        if resp_cat.status_code == 200:
            categories = resp_cat.json()

        params = {}
        if search:
            params['search'] = search
        if selected_category:
            params['category__name'] = selected_category
        if is_organic:
            params['is_organic'] = 'true'
        if exclude_allergens:
            params['exclude_allergen'] = exclude_allergens

        resp_prod = requests.get(f"{PLATFORM_API_URL}/api/products/", params=params, timeout=5)
        if resp_prod.status_code == 200:
            products = resp_prod.json()
        else:
            error = _api_error_message(resp_prod.status_code)

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Please check the service is running."
    except requests.exceptions.Timeout:
        error = "The request took too long to respond. Please try again."
    except requests.exceptions.RequestException:
        error = "A network error occurred. Please try again."
    except Exception:
        error = "An unexpected error occurred. Please try again or contact support if the problem persists."

    return render(request, 'web/index.html', {
        'products': products,
        'categories': categories,
        'error': error,
        'search': search,
        'selected_category': selected_category,
        'is_organic': is_organic,
        'exclude_allergens': exclude_allergens,
        'allergen_list': UK_ALLERGENS,
        'media_base_url': MEDIA_BASE_URL,
    })


def product_detail(request, product_id):
    """
    Individual product detail page.
    Fetches a single product and its reviews from the platform API.
    Calculates food miles between customer and producer postcodes.
    """
    product = None
    reviews = []
    recipes = []
    error = None
    food_miles = None

    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/products/{product_id}/", timeout=5)
        if resp.status_code == 200:
            product = resp.json()
        elif resp.status_code == 404:
            error = "This product could not be found."
        else:
            error = _api_error_message(resp.status_code)

        if product:
            resp_rev = requests.get(
                f"{PLATFORM_API_URL}/api/reviews/",
                params={'product': product_id},
                timeout=5
            )
            if resp_rev.status_code == 200:
                reviews = resp_rev.json()

            resp_rec = requests.get(
                f"{PLATFORM_API_URL}/api/products/recipes/",
                params={'products__id': product_id},
                timeout=5
            )
            if resp_rec.status_code == 200:
                recipes = resp_rec.json()

            # Calculate food miles if customer is logged in
            if request.session.get('token') and request.session.get('role') == 'CUSTOMER':
                try:
                    user_resp = requests.get(
                        f"{PLATFORM_API_URL}/api/auth/me/",
                        headers=get_auth_headers(request),
                        timeout=5
                    )
                    if user_resp.status_code == 200:
                        user_data = user_resp.json()
                        customer_postcode = (user_data.get('customer_profile') or {}).get('postcode')
                        producer_postcode = (product.get('producer_profile') or {}).get('postcode')
                        if customer_postcode and producer_postcode:
                            food_miles = _calculate_food_miles(customer_postcode, producer_postcode)
                except Exception:
                    pass

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Please check the service is running."
    except requests.exceptions.Timeout:
        error = "The request took too long to respond. Please try again."
    except requests.exceptions.RequestException:
        error = "A network error occurred. Please try again."
    except Exception:
        error = "An unexpected error occurred. Please try again or contact support if the problem persists."

    return render(request, 'web/product_detail.html', {
        'product': product,
        'reviews': reviews,
        'recipes': recipes,
        'error': error,
        'food_miles': food_miles,
        'media_base_url': MEDIA_BASE_URL,
    })


def login_view(request):
    if request.session.get('token'):
        return redirect('/')

    error = None
    username = ''

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        try:
            resp = requests.post(
                f"{PLATFORM_API_URL}/api/auth/login/",
                json={'username': username, 'password': password},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                request.session['token'] = data['access']
                request.session['username'] = username

                role = 'CUSTOMER'
                try:
                    profile_resp = requests.get(
                        f"{PLATFORM_API_URL}/api/auth/me/",
                        headers={'Authorization': f"Bearer {data['access']}"},
                        timeout=5
                    )
                    if profile_resp.status_code == 200:
                        profile_data = profile_resp.json()
                        role = profile_data.get('role', 'CUSTOMER')
                        request.session['user_id'] = profile_data.get('id')
                except:
                    pass

                request.session['role'] = role

                if role == 'PRODUCER':
                    return redirect('/dashboard/')
                return redirect('/')
            elif resp.status_code == 401:
                error = "Incorrect username or password. Please try again."
            else:
                error = _api_error_message(resp.status_code)

        except requests.exceptions.ConnectionError:
            error = "Cannot reach the platform API. Please check the service is running."
        except requests.exceptions.Timeout:
            error = "The request took too long to respond. Please try again."
        except requests.exceptions.RequestException:
            error = "A network error occurred. Please try again."
        except Exception:
            error = "An unexpected error occurred. Please try again or contact support if the problem persists."

    return render(request, 'web/login.html', {'error': error, 'username': username})


def logout_view(request):
    request.session.flush()
    return redirect('/')


def register_view(request):
    if request.session.get('token'):
        return redirect('/')

    error = None
    success = None
    form_data = {}

    if request.method == 'POST':
        role = request.POST.get('role', 'CUSTOMER')
        form_data = {
            'username': request.POST.get('username', '').strip(),
            'email': request.POST.get('email', '').strip(),
            'phone_number': request.POST.get('phone_number', '').strip(),
            'role': role,
        }

        if role == 'CUSTOMER':
            form_data['first_name'] = request.POST.get('first_name', '').strip()
            form_data['last_name'] = request.POST.get('last_name', '').strip()
            form_data['customer_delivery_address'] = request.POST.get('customer_delivery_address', '').strip()
            form_data['customer_postcode'] = request.POST.get('customer_postcode', '').strip()

            payload = {
                'username': form_data['username'],
                'password': request.POST.get('password', ''),
                'email': form_data['email'],
                'phone_number': form_data['phone_number'],
                'role': 'CUSTOMER',
                'customer_profile': {
                    'first_name': form_data['first_name'],
                    'last_name': form_data['last_name'],
                    'delivery_address': form_data['customer_delivery_address'],
                    'postcode': form_data['customer_postcode'],
                }
            }
        elif role == 'PRODUCER':
            form_data['business_name'] = request.POST.get('business_name', '').strip()
            form_data['business_address'] = request.POST.get('business_address', '').strip()
            form_data['producer_postcode'] = request.POST.get('producer_postcode', '').strip()
            form_data['bio'] = request.POST.get('bio', '').strip()

            payload = {
                'username': form_data['username'],
                'password': request.POST.get('password', ''),
                'email': form_data['email'],
                'phone_number': form_data['phone_number'],
                'role': 'PRODUCER',
                'producer_profile': {
                    'business_name': form_data['business_name'],
                    'business_address': form_data['business_address'],
                    'postcode': form_data['producer_postcode'],
                    'bio': form_data['bio'],
                }
            }
        elif role == 'COMMUNITY-GROUP-REPRESENTATIVE':
            form_data['organization_name'] = request.POST.get('organization_name', '').strip()
            form_data['organization_type'] = request.POST.get('organization_type', '').strip()
            form_data['community_delivery_address'] = request.POST.get('community_delivery_address', '').strip()
            form_data['community_postcode'] = request.POST.get('community_postcode', '').strip()

            payload = {
                'username': form_data['username'],
                'password': request.POST.get('password', ''),
                'email': form_data['email'],
                'phone_number': form_data['phone_number'],
                'role': 'COMMUNITY-GROUP-REPRESENTATIVE',
                'community_profile': {
                    'organization_name': form_data['organization_name'],
                    'organization_type': form_data['organization_type'],
                    'delivery_address': form_data['community_delivery_address'],
                    'postcode': form_data['community_postcode'],
                }
            }

        try:
            resp = requests.post(f"{PLATFORM_API_URL}/api/auth/register/", json=payload, timeout=5)
            if resp.status_code == 201:
                success = "Account created! You can now sign in."
                form_data = {}
            elif resp.status_code == 400:
                errors = resp.json()
                error = ". ".join(
                    f"{field}: {', '.join(msgs) if isinstance(msgs, list) else msgs}"
                    for field, msgs in errors.items()
                )
            else:
                error = _api_error_message(resp.status_code)

        except requests.exceptions.ConnectionError:
            error = "Cannot reach the platform API. Please check the service is running."
        except requests.exceptions.Timeout:
            error = "The request took too long to respond. Please try again."
        except requests.exceptions.RequestException:
            error = "A network error occurred. Please try again."
        except Exception:
            error = "An unexpected error occurred. Please try again or contact support if the problem persists."

    return render(request, 'web/register.html', {
        'error': error,
        'success': success,
        'form_data': form_data,
    })


def profile_view(request):
    if not request.session.get('token'):
        return redirect('/login/')

    headers = get_auth_headers(request)
    error = None
    success = None
    user = None

    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/auth/me/", headers=headers, timeout=5)
        if resp.status_code == 200:
            user = resp.json()
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
    except Exception as e:
        error = f"Could not load profile: {str(e)}"

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_details':
            payload = {
                'email': request.POST.get('email', '').strip(),
                'phone_number': request.POST.get('phone_number', '').strip(),
            }
            role = request.session.get('role')
            if role == 'CUSTOMER':
                payload['customer_profile'] = {
                    'first_name': request.POST.get('first_name', '').strip(),
                    'last_name': request.POST.get('last_name', '').strip(),
                    'delivery_address': request.POST.get('delivery_address', '').strip(),
                    'postcode': request.POST.get('postcode', '').strip(),
                }
            elif role == 'PRODUCER':
                payload['producer_profile'] = {
                    'business_name': request.POST.get('business_name', '').strip(),
                    'business_address': request.POST.get('business_address', '').strip(),
                    'postcode': request.POST.get('postcode', '').strip(),
                    'bio': request.POST.get('bio', '').strip(),
                }
            elif role == 'COMMUNITY-GROUP-REPRESENTATIVE':
                payload['community_profile'] = {
                    'organization_name': request.POST.get('organization_name', '').strip(),
                    'organization_type': request.POST.get('organization_type', '').strip(),
                    'delivery_address': request.POST.get('delivery_address', '').strip(),
                    'postcode': request.POST.get('postcode', '').strip(),
                }
            try:
                resp = requests.patch(
                    f"{PLATFORM_API_URL}/api/auth/me/",
                    json=payload,
                    headers=headers,
                    timeout=5
                )
                if resp.status_code == 200:
                    success = "Your details have been updated."
                    user = resp.json()
                else:
                    try:
                        err_data = resp.json()
                        messages = []
                        for field, errs in err_data.items():
                            if isinstance(errs, dict):
                                for subfield, suberrs in errs.items():
                                    if isinstance(suberrs, list):
                                        messages.append(f"{subfield.replace('_', ' ').title()}: {suberrs[0]}")
                                    else:
                                        messages.append(str(suberrs))
                            elif isinstance(errs, list):
                                messages.append(f"{field.replace('_', ' ').title()}: {errs[0]}")
                            else:
                                messages.append(str(errs))
                        error = " ".join(messages) if messages else "Could not update details."
                    except Exception:
                        error = "Could not update details. Please check your inputs and try again."
            except Exception as e:
                error = f"Unexpected error: {str(e)}"

        elif action == 'change_password':
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            if new_password != confirm_password:
                error = "Passwords do not match."
            elif len(new_password) < 8:
                error = "Password must be at least 8 characters."
            else:
                try:
                    resp = requests.patch(
                        f"{PLATFORM_API_URL}/api/auth/me/",
                        json={'password': new_password},
                        headers=headers,
                        timeout=5
                    )
                    if resp.status_code == 200:
                        success = "Password changed successfully."
                    else:
                        error = f"Could not change password: {resp.text}"
                except Exception as e:
                    error = f"Unexpected error: {str(e)}"

        elif action == 'delete_account':
            try:
                resp = requests.delete(f"{PLATFORM_API_URL}/api/auth/me/", headers=headers, timeout=5)
                if resp.status_code == 204:
                    request.session.flush()
                    return redirect('/')
                else:
                    error = "Could not delete account. Please try again."
            except Exception as e:
                error = f"Unexpected error: {str(e)}"

        elif action == 'update_notification_prefs':
            user_id = request.session.get('user_id')
            if user_id:
                payload = {
                    'user_id':        user_id,
                    'email_enabled':  request.POST.get('email_enabled') == 'on',
                    'in_app_enabled': request.POST.get('in_app_enabled') == 'on',
                }
                try:
                    resp = requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/",
                        json=payload,
                        timeout=5
                    )
                    if resp.status_code == 200:
                        success = "Notification preferences saved."
                    else:
                        error = "Could not save notification preferences."
                except Exception as e:
                    error = f"Unexpected error: {str(e)}"

        elif action == 'update_notification_type_prefs_bulk':
            user_id = request.session.get('user_id')
            notification_types = request.POST.getlist('notification_types')
            if user_id and notification_types:
                failed = False
                for ntype in notification_types:
                    payload = {
                        'user_id':           user_id,
                        'notification_type': ntype,
                        'email_enabled':     request.POST.get(f'email_{ntype}') == 'on',
                        'in_app_enabled':    request.POST.get(f'in_app_{ntype}') == 'on',
                    }
                    try:
                        resp = requests.post(
                            f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/types/",
                            json=payload,
                            timeout=5
                        )
                        if resp.status_code != 200:
                            failed = True
                    except Exception:
                        failed = True
                success = "Notification preferences saved." if not failed else None
                if failed:
                    error = "Some preferences could not be saved."

        elif action == 'update_notification_prefs_all':
            user_id = request.session.get('user_id')
            if user_id:
                global_email  = request.POST.get('email_enabled') == 'on'
                global_in_app = request.POST.get('in_app_enabled') == 'on'
                failed = False

                try:
                    resp = requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/",
                        json={
                            'user_id':        user_id,
                            'email_enabled':  global_email,
                            'in_app_enabled': global_in_app,
                        },
                        timeout=5
                    )
                    if resp.status_code != 200:
                        failed = True
                except Exception:
                    failed = True

                notification_types = request.POST.getlist('notification_types')
                for ntype in notification_types:
                    type_email  = request.POST.get(f'email_{ntype}') == 'on'
                    type_in_app = request.POST.get(f'in_app_{ntype}') == 'on'
                    if not global_email:
                        type_email = False
                    if not global_in_app:
                        type_in_app = False
                    try:
                        resp = requests.post(
                            f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/types/",
                            json={
                                'user_id':           user_id,
                                'notification_type': ntype,
                                'email_enabled':     type_email,
                                'in_app_enabled':    type_in_app,
                            },
                            timeout=5
                        )
                        if resp.status_code != 200:
                            failed = True
                    except Exception:
                        failed = True

                success = "Notification settings saved." if not failed else None
                if failed:
                    error = "Some preferences could not be saved."

    notif_prefs = {'email_enabled': True, 'in_app_enabled': True}
    notif_type_prefs = {}
    user_id = request.session.get('user_id')
    if user_id:
        try:
            resp = requests.get(
                f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/",
                params={'user_id': user_id},
                timeout=5
            )
            if resp.status_code == 200:
                notif_prefs = resp.json()
        except Exception:
            pass
        try:
            resp = requests.get(
                f"{NOTIFICATIONS_API_URL}/api/notifications/preferences/types/",
                params={'user_id': user_id},
                timeout=5
            )
            if resp.status_code == 200:
                for tp in resp.json():
                    notif_type_prefs[tp['notification_type']] = tp
        except Exception:
            pass

    CUSTOMER_NOTIFICATION_TYPES = [
        ('PAYMENT_RECEIVED',          'Payment Confirmed',          'Email confirmation when your payment is successfully processed'),
        ('PAYMENT_FAILED',            'Payment Failed',             'Email alert when a payment could not be completed'),
        ('ORDER_SUMMARY',             'Order Summary',              'Itemised order breakdown email sent after a successful payment'),
        ('SURPLUS_DEAL',              'Surplus Deals',              'Alerts when a producer marks a product as a surplus deal'),
        ('ORDER_CONFIRMED',           'Order Confirmed',            'Notifications when your order has been confirmed by the producer'),
        ('ORDER_READY',               'Order Ready',                'Notifications when your order is ready for collection or delivery'),
        ('ORDER_DELIVERED',           'Order Delivered',            'Notifications when your order has been marked as delivered'),
        ('ORDER_CANCELLED',           'Order Cancelled',            'Notifications when an order is cancelled'),
        ('RECURRING_ORDER_REMINDER',  'Recurring Order Reminder',   'Day-before reminder when a recurring order is about to be placed automatically'),
        ('RECURRING_ORDER_PLACED',    'Recurring Order Placed',     'Confirmation with full order summary when a recurring order fires successfully'),
        ('RECURRING_ORDER_PAUSED',    'Recurring Order Paused',     'Alert when a recurring order is paused due to an item being unavailable or out of stock'),
    ]
    PRODUCER_NOTIFICATION_TYPES = [
        ('ORDER_PLACED',      'Order Placed',      'Alerts when a customer places a new order with you'),
        ('LOW_STOCK',         'Low Stock',         'Alerts when a product\'s stock drops below your set threshold'),
        ('OUT_OF_STOCK',      'Out of Stock',      'Alerts when a product runs out of stock'),
        ('SEASONAL_REMINDER', 'Seasonal Reminder', 'Reminders when your seasonal products are coming into season'),
    ]

    role = user.get('role', 'CUSTOMER') if user else 'CUSTOMER'
    definitions = PRODUCER_NOTIFICATION_TYPES if role == 'PRODUCER' else CUSTOMER_NOTIFICATION_TYPES

    type_prefs_list = []
    for ntype, label, desc in definitions:
        tp = notif_type_prefs.get(ntype)
        type_prefs_list.append({
            'type':           ntype,
            'label':          label,
            'desc':           desc,
            'email_enabled':  tp['email_enabled']  if tp else notif_prefs.get('email_enabled', True),
            'in_app_enabled': tp['in_app_enabled'] if tp else notif_prefs.get('in_app_enabled', True),
            'has_override':   tp is not None,
        })

    return render(request, 'web/profile.html', {
        'user':             user,
        'error':            error,
        'success':          success,
        'notif_prefs':      notif_prefs,
        'type_prefs_list':  type_prefs_list,
    })


def admin_dashboard(request):
    """Admin dashboard with tabs for users, products, orders, transactions, and site stats."""
    """Admin dashboard with commission monitoring."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')

    headers = get_auth_headers(request)
    users, products, orders, transactions = [], [], [], []
    error = None
    transaction_error = None
    transaction_debug = []

    try:
        resp_users = requests.get(f"{PLATFORM_API_URL}/api/auth/users/", headers=headers, timeout=5)
        if resp_users.status_code == 200:
            users = resp_users.json()

        resp_products = requests.get(f"{PLATFORM_API_URL}/api/products/", headers=headers, timeout=5)
        if resp_products.status_code == 200:
            products = resp_products.json()

        resp_orders = requests.get(f"{PLATFORM_API_URL}/api/orders/", headers=headers, timeout=5)
        if resp_orders.status_code == 200:
            orders = resp_orders.json()

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Please check the service is running."
    except requests.exceptions.Timeout:
        error = "A service request timed out while loading the admin dashboard."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    for base_url in _candidate_payment_gateway_api_bases():
        transactions_url = f"{base_url}/payments/api/transactions/?limit=50"
        try:
            resp_transactions = requests.get(transactions_url, timeout=8)
        except requests.exceptions.ConnectionError:
            transaction_debug.append(f"{transactions_url} -> connection error")
            continue
        except requests.exceptions.Timeout:
            transaction_debug.append(f"{transactions_url} -> timed out")
            continue
        except Exception as exc:
            transaction_debug.append(f"{transactions_url} -> unexpected error: {str(exc)}")
            continue

        if resp_transactions.status_code == 200:
            trans_data = resp_transactions.json()
            transactions = trans_data.get('transactions', [])
            break

        tx_error = _extract_error_from_response(
            resp_transactions,
            'Unknown payment-gateway error.',
        )
        transaction_debug.append(
            f"{transactions_url} -> status {resp_transactions.status_code}: {tx_error}"
        )

    if not transactions and transaction_debug:
        transaction_error = "Transactions could not be loaded from payment-gateway."

    total_revenue = sum(float(o.get('total_amount', 0)) for o in orders)
    total_commission = sum(float(o.get('commission_total') or 0) for o in orders)
    total_producer_payout = total_revenue - total_commission
    customers = [u for u in users if u.get('role') == 'CUSTOMER']
    producers = [u for u in users if u.get('role') == 'PRODUCER']
    community_group_representatives = [u for u in users if u.get('role') == 'COMMUNITY-GROUP-REPRESENTATIVE']

    producer_breakdown = {}
    producer_food_miles = {}
    total_food_miles = 0

    for o in orders:
        producer = o.get('producer_name') or o.get('producer') or 'Unknown'
        if producer not in producer_breakdown:
            producer_breakdown[producer] = {'producer': producer, 'order_count': 0, 'total_revenue': 0.0, 'total_commission': 0.0, 'total_payout': 0.0}
        rev = float(o.get('total_amount', 0))
        com = float(o.get('commission_total') or 0)
        producer_breakdown[producer]['order_count'] += 1
        producer_breakdown[producer]['total_revenue'] += rev
        producer_breakdown[producer]['total_commission'] += com
        producer_breakdown[producer]['total_payout'] += (rev - com)

        # Food miles — only DELIVERED delivery orders
        status = (o.get('status') or '').upper()
        collection_type = (o.get('collection_type') or '').lower()
        if status == 'DELIVERED' and 'collect' not in collection_type:
            miles = float(o.get('food_miles') or 0)
            if miles:
                total_food_miles += miles
                if producer not in producer_food_miles:
                    producer_food_miles[producer] = 0
                producer_food_miles[producer] += miles

    producer_breakdown_list = sorted(producer_breakdown.values(), key=lambda x: x['total_commission'], reverse=True)
    producer_food_miles_list = sorted(
        [{'producer': k, 'miles': round(v, 1)} for k, v in producer_food_miles.items()],
        key=lambda x: x['miles'], reverse=True
    )

    # Fetch settlement history and any unsettled payment count
    settlements = []
    settlement_error = None
    for base_url in _candidate_payment_gateway_api_bases():
        try:
            resp_s = requests.get(f"{base_url}/payments/api/settlements/", timeout=8)
            if resp_s.status_code == 200:
                settlements = resp_s.json().get('settlements', [])
                break
        except Exception:
            continue

    unsettled_count = 0
    for base_url in _candidate_payment_gateway_api_bases():
        try:
            resp_u = requests.get(f"{base_url}/payments/api/unsettled/", timeout=8)
            if resp_u.status_code == 200:
                unsettled_count = len(resp_u.json().get('payments', []))
                break
        except Exception:
            continue

    settlement_message = request.GET.get('settlement_msg', '')
    if not settlement_message:
        settlement_error = request.GET.get('settlement_error', '')

    return render(request, 'web/admin.html', {
        'users': users,
        'products': products,
        'orders': orders,
        'transactions': transactions,
        'transaction_error': transaction_error,
        'transaction_debug': transaction_debug,
        'all_orders': orders,
        'error': error,
        'total_revenue': total_revenue,
        'total_commission': total_commission,
        'total_producer_payout': total_producer_payout,
        'producer_breakdown': producer_breakdown_list,
        'customer_count': len(customers),
        'producer_count': len(producers),
        'community_group_representative_count': len(community_group_representatives),
        'total_food_miles': round(total_food_miles, 1),
        'producer_food_miles': producer_food_miles_list,
        'media_base_url': MEDIA_BASE_URL,
        'settlements': settlements,
        'settlement_message': settlement_message,
        'settlement_error': settlement_error,
        'unsettled_count': unsettled_count,
    })


def admin_run_weekly_settlement(request):
    """Compile outstanding paid transactions into a settlement and send to payment-gateway."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')
    if request.method != 'POST':
        return redirect('/admin-dashboard/')

    headers = get_auth_headers(request)

    # 1. Get unsettled successful payments from payment-gateway
    unsettled_payments = []
    for base_url in _candidate_payment_gateway_api_bases():
        try:
            resp = requests.get(f"{base_url}/payments/api/unsettled/", timeout=10)
            if resp.status_code == 200:
                unsettled_payments = resp.json().get('payments', [])
                break
        except Exception:
            continue

    if not unsettled_payments:
        return redirect('/admin-dashboard/?settlement_msg=No+outstanding+paid+transactions+to+settle')

    # 2. Fetch all platform orders (each has customer_order FK + producer info)
    all_orders = []
    try:
        resp_o = requests.get(f"{PLATFORM_API_URL}/api/orders/", headers=headers, timeout=10)
        if resp_o.status_code == 200:
            all_orders = resp_o.json()
    except Exception:
        pass

    # 3. Fetch users to build producer stripe_account_id lookup
    all_users = []
    try:
        resp_u = requests.get(f"{PLATFORM_API_URL}/api/auth/users/", headers=headers, timeout=5)
        if resp_u.status_code == 200:
            all_users = resp_u.json()
    except Exception:
        pass

    producer_stripe_map = {}
    for u in all_users:
        if u.get('role') == 'PRODUCER':
            profile = u.get('producer_profile') or {}
            producer_stripe_map[str(u['id'])] = {
                'producer_name': profile.get('business_name') or u.get('username', ''),
                'stripe_account_id': profile.get('stripe_account_id', ''),
            }

    # 4. Build set of CustomerOrder IDs covered by unsettled payments
    unsettled_order_ids = {str(p['order_id']) for p in unsettled_payments if p.get('order_id')}
    payment_ids = [p['payment_id'] for p in unsettled_payments]

    # 5. Compile per-producer totals using platform orders
    producer_totals = {}
    for o in all_orders:
        co_id = str(o.get('customer_order', '') or '')
        if not co_id or co_id not in unsettled_order_ids:
            continue
        producer_id = str(o.get('producer_id') or o.get('producer') or '')
        if not producer_id:
            continue
        total = float(o.get('total_amount', 0) or 0)
        commission = float(o.get('commission_total', 0) or 0)
        payout = total - commission  # 95%
        if producer_id not in producer_totals:
            info = producer_stripe_map.get(producer_id, {})
            producer_totals[producer_id] = {
                'producer_id': producer_id,
                'producer_name': info.get('producer_name') or f'Producer {producer_id}',
                'stripe_account_id': info.get('stripe_account_id', ''),
                'amount': 0.0,
            }
        producer_totals[producer_id]['amount'] += payout

    if not producer_totals:
        return redirect(
            '/admin-dashboard/?settlement_error=' +
            quote('Could not match paid transactions to any platform orders. Ensure order IDs match.')
        )

    # 6. POST compiled settlement to payment-gateway
    settlement_payload = {
        'payment_ids': payment_ids,
        'producers': [
            {**v, 'amount': str(round(v['amount'], 2))}
            for v in producer_totals.values()
        ],
    }

    settlement_resp = None
    for base_url in _candidate_payment_gateway_api_bases():
        try:
            settlement_resp = requests.post(
                f"{base_url}/payments/api/settlements/run/",
                json=settlement_payload,
                timeout=30,
            )
            break
        except Exception:
            continue

    if settlement_resp and settlement_resp.status_code == 200:
        data = settlement_resp.json()
        msg = quote(f"Settlement #{data.get('settlement_id')} completed — £{data.get('total_amount')} across {data.get('producer_count')} producer(s)")
        return redirect(f'/admin-dashboard/?settlement_msg={msg}')

    err = 'Settlement failed — could not reach payment gateway'
    if settlement_resp:
        err = f'Settlement failed (status {settlement_resp.status_code})'
        try:
            details = settlement_resp.json().get('error', '')
            if details:
                err = f'{err}: {details}'
        except Exception:
            if settlement_resp.text:
                err = f'{err}: {settlement_resp.text[:180]}'
    return redirect(f'/admin-dashboard/?settlement_error={quote(err)}')


def admin_commission_export(request):
    """Export commission data as CSV."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')
    orders = []
    headers = get_auth_headers(request)

    try:
        resp_orders = requests.get(f"{PLATFORM_API_URL}/api/orders/", headers=headers, timeout=5)
        if resp_orders.status_code == 200:
            orders = resp_orders.json()
    except Exception:
        pass

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if date_from:
        orders = [o for o in orders if (o.get('created_at') or '')[:10] >= date_from]
    if date_to:
        orders = [o for o in orders if (o.get('created_at') or '')[:10] <= date_to]

    response = HttpResponse(content_type='text/csv')
    filename = f"brfn_commission_{date.today()}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Order ID', 'Date', 'Customer', 'Producer', 'Status', 'Order Total (£)', 'Commission 5% (£)', 'Producer Payout 95% (£)'])

    for o in orders:
        total = float(o.get('total_amount', 0))
        commission = float(o.get('commission_total') or 0)
        payout = total - commission
        writer.writerow([
            f"#{o.get('id', '')}",
            (o.get('created_at') or '')[:10],
            o.get('customer_username') or o.get('customer', ''),
            o.get('producer_name') or '—',
            o.get('status', ''),
            f"{total:.2f}",
            f"{commission:.2f}",
            f"{payout:.2f}",
        ])

    return response


def admin_delete_user(request, user_id):
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')
    if request.method == 'POST':
        try:
            requests.delete(
                f"{PLATFORM_API_URL}/api/auth/users/{user_id}/",
                headers=get_auth_headers(request),
                timeout=5
            )
        except Exception:
            pass
    return redirect('/admin-dashboard/')


def admin_edit_user(request, user_id):
    """Admin-only: edit a user's details, profile and role."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')
    if request.method == 'POST':
        role = request.POST.get('role', 'CUSTOMER')
        payload = {
            'username': request.POST.get('username', '').strip(),
            'email': request.POST.get('email', '').strip(),
            'phone_number': request.POST.get('phone_number', '').strip(),
            'role': role,
        }
        if role == 'CUSTOMER':
            payload['customer_profile'] = {
                'first_name': request.POST.get('first_name', '').strip(),
                'last_name': request.POST.get('last_name', '').strip(),
                'delivery_address': request.POST.get('customer_delivery_address', '').strip(),
                'postcode': request.POST.get('customer_postcode', '').strip(),
            }
        elif role == 'PRODUCER':
            payload['producer_profile'] = {
                'business_name': request.POST.get('business_name', '').strip(),
                'business_address': request.POST.get('business_address', '').strip(),
                'postcode': request.POST.get('producer_postcode', '').strip(),
                'bio': request.POST.get('bio', '').strip(),
                'stripe_account_id': request.POST.get('stripe_account_id', '').strip(),
            }
        elif role == 'COMMUNITY-GROUP-REPRESENTATIVE':
            payload['community_profile'] = {
                'organization_name': request.POST.get('organization_name', '').strip(),
                'organization_type': request.POST.get('organization_type', '').strip(),
                'delivery_address': request.POST.get('community_delivery_address', '').strip(),
                'postcode': request.POST.get('community_postcode', '').strip(),
            }
        try:
            requests.patch(
                f"{PLATFORM_API_URL}/api/auth/users/{user_id}/",
                json=payload,
                headers=get_auth_headers(request),
                timeout=5
            )
        except Exception:
            pass
    return redirect('/admin-dashboard/')


def admin_delete_product(request, product_id):
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')
    if request.method == 'POST':
        try:
            requests.delete(
                f"{PLATFORM_API_URL}/api/products/{product_id}/",
                headers=get_auth_headers(request),
                timeout=5
            )
        except Exception:
            pass
    return redirect('/admin-dashboard/')


def producer_dashboard(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')

    products = []
    error = None
    username = request.session.get('username')
    producer_id = str(request.session.get('user_id') or '')
    payouts = []
    payout_total = 0.0
    transferred_count = 0

    try:
        resp = requests.get(
            f"{PLATFORM_API_URL}/api/products/",
            params={'producer__username': username},
            timeout=5
        )
        if resp.status_code == 200:
            products = resp.json()
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load your products (status {resp.status_code})."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    # Read settlement history from payment gateway and show only this producer's rows.
    if producer_id:
        settlements = []
        for base_url in _candidate_payment_gateway_api_bases():
            try:
                settlement_resp = requests.get(f"{base_url}/payments/api/settlements/", timeout=8)
                if settlement_resp.status_code == 200:
                    settlements = settlement_resp.json().get('settlements', [])
                    break
            except Exception:
                continue

        for settlement in settlements:
            for row in settlement.get('producers', []) or []:
                if str(row.get('producer_id') or '') != producer_id:
                    continue
                amount = float(row.get('amount') or 0)
                payout_total += amount
                if row.get('status') == 'TRANSFERRED':
                    transferred_count += 1
                payouts.append({
                    'settlement_id': settlement.get('id'),
                    'created_at': settlement.get('created_at', ''),
                    'week_start': settlement.get('week_start', ''),
                    'week_end': settlement.get('week_end', ''),
                    'amount': amount,
                    'status': row.get('status', ''),
                    'transfer_id': row.get('transfer_id', ''),
                    'error_message': row.get('error_message', ''),
                })

        payouts.sort(key=lambda r: (r.get('created_at') or ''), reverse=True)

    return render(request, 'web/dashboard.html', {
        'products': products,
        'error': error,
        'media_base_url': MEDIA_BASE_URL,
        'payouts': payouts,
        'payout_total': payout_total,
        'transferred_count': transferred_count,
    })


def add_product_view(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')

    categories = []
    error = None
    success = False

    try:
        resp_cat = requests.get(f"{PLATFORM_API_URL}/api/products/categories/", timeout=5)
        if resp_cat.status_code == 200:
            categories = resp_cat.json()
    except Exception:
        pass

    if request.method == 'POST':
        form_data = request.POST.dict()
        form_data.pop('csrfmiddlewaretoken', None)
        form_data['is_organic'] = 'is_organic' in request.POST
        availability_status = request.POST.get('availability_status', 'ALWAYS')
        if availability_status == 'OUT_OF_STOCK':
            form_data['is_available'] = False
            form_data['seasonal_start_month'] = ''
            form_data['seasonal_end_month'] = ''
        elif availability_status == 'IN_SEASON':
            form_data['is_available'] = True
        else:
            form_data['is_available'] = True
            form_data['seasonal_start_month'] = ''
            form_data['seasonal_end_month'] = ''

        for key in ['harvest_date', 'best_before_date', 'unit', 'allergen_info', 'description']:
            if not form_data.get(key):
                form_data.pop(key, None)
        # seasonal months kept as '' so serializer converts to None to clear DB fields

        allergens = request.POST.getlist('allergens')
        form_data['allergens'] = json.dumps(allergens)

        is_surplus = 'is_surplus' in request.POST
        form_data['is_surplus'] = str(is_surplus).lower()
        if is_surplus:
            surplus_deal = {}
            if form_data.get('discount_percentage'):
                surplus_deal['discount_percentage'] = form_data.pop('discount_percentage')
            if form_data.get('surplus_expiry'):
                surplus_deal['expiry_date'] = form_data.pop('surplus_expiry')
            if form_data.get('surplus_note'):
                surplus_deal['deal_note'] = form_data.pop('surplus_note')
            if surplus_deal:
                for k, v in surplus_deal.items():
                    form_data[f'surplus_deal.{k}'] = v
        else:
            form_data.pop('discount_percentage', None)
            form_data.pop('surplus_expiry', None)
            form_data.pop('surplus_note', None)

        files = {}
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            files['image'] = (image_file.name, image_file.read(), image_file.content_type)

        try:
            resp = requests.post(
                f"{PLATFORM_API_URL}/api/products/",
                headers={'Authorization': f"Bearer {request.session.get('token')}"},
                data=form_data,
                files=files,
                timeout=10
            )
            if resp.status_code == 201:
                return redirect('/dashboard/')
            elif resp.status_code == 401:
                request.session.flush()
                return redirect('/login/')
            else:
                error_msg = resp.text
                try:
                    error_data = resp.json()
                    error_msg = str(error_data)
                except ValueError:
                    pass
                error = f"Failed to create product. Reason: {error_msg}"
        except Exception as e:
            error = f"Error sending data to Producer API: {str(e)}"

    return render(request, 'web/add_product.html', {
        'categories': categories,
        'error': error,
        'success': success,
        'allergen_list': UK_ALLERGENS,
    })


def edit_product_view(request, product_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')

    categories = []
    product = None
    error = None

    try:
        resp_cat = requests.get(f"{PLATFORM_API_URL}/api/products/categories/", timeout=5)
        if resp_cat.status_code == 200:
            categories = resp_cat.json()
    except Exception:
        pass

    try:
        resp_prod = requests.get(
            f"{PLATFORM_API_URL}/api/products/{product_id}/",
            headers={'Authorization': f"Bearer {request.session.get('token')}"},
            timeout=5
        )
        if resp_prod.status_code == 200:
            product = resp_prod.json()
        elif resp_prod.status_code == 404:
            return redirect('/dashboard/')
        elif resp_prod.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Failed to load product details: {resp_prod.status_code}"
    except Exception as e:
        error = f"Error communicating with API: {str(e)}"

    if request.method == 'POST':
        form_data = request.POST.dict()
        form_data.pop('csrfmiddlewaretoken', None)
        form_data['is_organic'] = 'is_organic' in request.POST
        availability_status = request.POST.get('availability_status', 'ALWAYS')
        if availability_status == 'OUT_OF_STOCK':
            form_data['is_available'] = False
            form_data['seasonal_start_month'] = ''
            form_data['seasonal_end_month'] = ''
        elif availability_status == 'IN_SEASON':
            form_data['is_available'] = True
        else:
            form_data['is_available'] = True
            form_data['seasonal_start_month'] = ''
            form_data['seasonal_end_month'] = ''

        for key in ['harvest_date', 'best_before_date', 'unit', 'allergen_info', 'description']:
            if not form_data.get(key):
                form_data.pop(key, None)
        # seasonal months kept as '' so serializer converts to None to clear DB fields

        allergens = request.POST.getlist('allergens')
        form_data['allergens'] = json.dumps(allergens)

        is_surplus = 'is_surplus' in request.POST
        form_data['is_surplus'] = str(is_surplus).lower()
        if is_surplus:
            surplus_deal = {}
            if form_data.get('discount_percentage'):
                surplus_deal['discount_percentage'] = form_data.pop('discount_percentage')
            if form_data.get('surplus_expiry'):
                surplus_deal['expiry_date'] = form_data.pop('surplus_expiry')
            if form_data.get('surplus_note'):
                surplus_deal['deal_note'] = form_data.pop('surplus_note')
            if surplus_deal:
                for k, v in surplus_deal.items():
                    form_data[f'surplus_deal.{k}'] = v
        else:
            form_data.pop('discount_percentage', None)
            form_data.pop('surplus_expiry', None)
            form_data.pop('surplus_note', None)

        files = {}
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            files['image'] = (image_file.name, image_file.read(), image_file.content_type)
        else:
            form_data.pop('image', None)

        try:
            resp = requests.patch(
                f"{PLATFORM_API_URL}/api/products/{product_id}/",
                headers={'Authorization': f"Bearer {request.session.get('token')}"},
                data=form_data,
                files=files if files else None,
                timeout=10
            )
            if resp.status_code == 200:
                return redirect('/dashboard/')
            elif resp.status_code == 401:
                request.session.flush()
                return redirect('/login/')
            else:
                error_msg = resp.text
                try:
                    error_data = resp.json()
                    error_msg = str(error_data)
                except ValueError:
                    pass
                error = f"Failed to update product. Reason: {error_msg}"
        except Exception as e:
            error = f"Error sending data to Producer API: {str(e)}"

    return render(request, 'web/edit_product.html', {
        'categories': categories,
        'product': product,
        'error': error,
        'media_base_url': MEDIA_BASE_URL,
        'allergen_list': UK_ALLERGENS,
    })


def delete_product_view(request, product_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    if request.method == 'POST':
        try:
            requests.delete(
                f"{PLATFORM_API_URL}/api/products/{product_id}/",
                headers={'Authorization': f"Bearer {request.session.get('token')}"},
                timeout=5
            )
        except Exception:
            pass
    return redirect('/dashboard/')


def basket_view(request):
    basket = None
    success = None
    error = None
    items_by_producer = None

    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to view your basket."})
    
    success = request.GET.get('success')
    error = request.GET.get('error')

    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=5)
        if resp.status_code == 200:
            basket = resp.json()
            items_by_producer = basket.get('items_by_producer')
        elif resp.status_code == 401:
            request.session.flush()
            return render(request, 'web/login.html', {'error': "Your session has expired. Please log in again."})
        elif resp.status_code == 403:
            return render(request, 'web/index.html', {'error': "Only customers can access baskets."})
        else:
            error = f"Unexpected error: could not load basket (status {resp.status_code})."
    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Is the platform-service running?"
    except requests.exceptions.Timeout:
        error = "The platform API took too long to respond."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/basket.html', {
        'basket': basket,
        'items_by_producer': items_by_producer,
        'error': error,
        'success': success,
        'media_base_url': MEDIA_BASE_URL,
    })


def add_to_basket(request, product_id):
    error = None
    success = None

    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to add items to your basket."})

    if request.method == 'POST':
        quantity = request.POST.get('quantity', 1)
        try:
            resp = requests.post(
                f"{PLATFORM_API_URL}/api/basket/add/",
                headers=get_auth_headers(request),
                json={'product_id': product_id, 'quantity': int(quantity)},
                timeout=5
            )
            if resp.status_code == 200:
                success = "Item successfully added to your basket! Go to your basket from the navigation bar to check it."
                product = None
                reviews = []
                try:
                    resp_prod = requests.get(f"{PLATFORM_API_URL}/api/products/{product_id}/", timeout=5)
                    if resp_prod.status_code == 200:
                        product = resp_prod.json()
                    resp_rev = requests.get(f"{PLATFORM_API_URL}/api/reviews/", params={'product': product_id}, timeout=5)
                    if resp_rev.status_code == 200:
                        reviews = resp_rev.json()
                except:
                    pass
                return render(request, 'web/product_detail.html', {
                    'product': product, 'reviews': reviews, 'success': success, 'media_base_url': MEDIA_BASE_URL,
                })
            elif resp.status_code == 401:
                request.session.flush()
                return render(request, 'web/login.html', {'error': "Your session has expired. Please log in again."})
            elif resp.status_code == 403:
                error = "Only customers can add items to basket."
            elif resp.status_code == 400:
                error = resp.json().get('error', 'Could not add item to basket.')
            else:
                error = f"Failed to add item (status {resp.status_code})."
        except requests.exceptions.ConnectionError:
            error = "Cannot reach the platform API. Is the platform-service running?"
        except requests.exceptions.Timeout:
            error = "The platform API took too long to respond."
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

    if error:
        product = None
        reviews = []
        try:
            resp = requests.get(f"{PLATFORM_API_URL}/api/products/{product_id}/", timeout=5)
            if resp.status_code == 200:
                product = resp.json()
            resp_rev = requests.get(f"{PLATFORM_API_URL}/api/reviews/", params={'product': product_id}, timeout=5)
            if resp_rev.status_code == 200:
                reviews = resp_rev.json()
        except:
            pass
        return render(request, 'web/product_detail.html', {
            'product': product, 'reviews': reviews, 'error': error, 'media_base_url': MEDIA_BASE_URL,
        })

    return redirect(f'/products/{product_id}/')


def update_basket_item(request, item_id):
    error = None
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to view your basket."})

    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        action = request.POST.get('action')
        if action == 'increase':
            new_quantity = quantity + 1
        elif action == 'decrease':
            new_quantity = quantity - 1
        else:
            new_quantity = quantity

        try:
            resp = requests.patch(
                f"{PLATFORM_API_URL}/api/basket/items/{item_id}/",
                headers=get_auth_headers(request),
                json={'quantity': new_quantity},
                timeout=5
            )
            if resp.status_code == 200:
                return redirect('/basket/')
            elif resp.status_code == 400:
                error = resp.json().get('error', 'Could not update item.')
            else:
                error = f"Failed to update item (status {resp.status_code})."
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

    if error:
        basket = None
        items_by_producer = []
        try:
            resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=5)
            if resp.status_code == 200:
                basket = resp.json()
                items_by_producer = basket.get('items_by_producer', [])
        except:
            pass
        return render(request, 'web/basket.html', {
            'basket': basket, 'error': error, 'items_by_producer': items_by_producer, 'media_base_url': MEDIA_BASE_URL,
        })

    return redirect('/basket/')


def remove_from_basket(request, item_id):
    error = None
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to view your basket."})

    if request.method == 'POST':
        try:
            resp = requests.delete(
                f"{PLATFORM_API_URL}/api/basket/items/{item_id}/remove/",
                headers=get_auth_headers(request),
                timeout=5
            )
            if resp.status_code == 200:
                return redirect('/basket/')
            else:
                error = "Could not remove item."
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

    if error:
        basket = None
        try:
            resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=5)
            if resp.status_code == 200:
                basket = resp.json()
        except:
            pass
        return render(request, 'web/basket.html', {'basket': basket, 'error': error, 'media_base_url': MEDIA_BASE_URL})

    return redirect('/basket/')


def clear_basket(request):
    success = None
    error = None
    basket = None

    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to view your basket."})

    if request.method == 'POST':
        try:
            resp = requests.delete(f"{PLATFORM_API_URL}/api/basket/clear/", headers=get_auth_headers(request), timeout=5)
            resp_basket = requests.get(f"{PLATFORM_API_URL}/api/basket/", timeout=5)
            if resp_basket.status_code == 200:
                basket = resp_basket.json()
            if resp.status_code == 200:
                success = "Successfully cleared all items from your basket!"
                return render(request, 'web/basket.html', {'basket': basket, 'success': success, 'media_base_url': MEDIA_BASE_URL})
            else:
                error = "Could not clear basket."
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

    if error:
        basket = None
        try:
            resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=5)
            if resp.status_code == 200:
                basket = resp.json()
        except:
            pass
        return render(request, 'web/basket.html', {'basket': basket, 'error': error, 'media_base_url': MEDIA_BASE_URL})

    return redirect('/basket/')


def checkout_view(request):
    """
    Display the customer's basket with all items.
    Calculates food miles per producer group.
    """
    basket = None
    error = request.GET.get('error')
    items_by_producer = None
    food_miles_by_producer = {}
    minimum_delivery_date = (date.today() + timedelta(days=2)).isoformat()

    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to checkout."})

    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=5)
        if resp.status_code == 200:
            basket = resp.json()
            items_by_producer = basket.get('items_by_producer')

            if items_by_producer:
                try:
                    user_resp = requests.get(
                        f"{PLATFORM_API_URL}/api/auth/me/",
                        headers=get_auth_headers(request),
                        timeout=5
                    )
                    if user_resp.status_code == 200:
                        profile_data = user_resp.json()
                        customer_postcode = (
                            (profile_data.get('customer_profile') or {}).get('postcode')
                            or (profile_data.get('community_profile') or {}).get('postcode')
                        )
                        if customer_postcode:
                            for group in items_by_producer:
                                producer_postcode = (group.get('producer_profile') or {}).get('postcode')
                                miles = _calculate_food_miles(customer_postcode, producer_postcode) if producer_postcode else None
                                food_miles_by_producer[str(group.get('producer_id'))] = miles
                except Exception:
                    pass

        elif resp.status_code == 401:
            request.session.flush()
            return render(request, 'web/login.html', {'error': "Your session has expired. Please log in again."})
        else:
            error = f"Unexpected error: could not load checkout page (status {resp.status_code})."

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Is the platform-service running?"
    except requests.exceptions.Timeout:
        error = "The platform API took too long to respond."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/checkout.html', {
        'basket': basket,
        'items_by_producer': items_by_producer,
        'minimum_delivery_date': minimum_delivery_date,
        'food_miles_by_producer': json.dumps(food_miles_by_producer),
        'error': error,
        'media_base_url': MEDIA_BASE_URL,
    })


def create_order(request):
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to place an order."})

    if request.method != 'POST':
        return redirect('/basket/checkout/')

    error = None
    delivery_dates = {}
    collection_types = {}
    delivery_instructions = {}

    for key, value in request.POST.items():
        if key.startswith('delivery_date_'):
            producer_id = key.replace('delivery_date_', '')
            delivery_dates[producer_id] = value
        elif key.startswith('collection_type_'):
            producer_id = key.replace('collection_type_', '')
            collection_types[producer_id] = value
        elif key.startswith('delivery_instructions_'):
            producer_id = key.replace('delivery_instructions_', '')
            delivery_instructions[producer_id] = value.strip() or None
        
        make_recurring = request.POST.get('make_recurring') == 'on'
        order_day = request.POST.get('order_day')
        delivery_day = request.POST.get('delivery_day')

    try:
        basket_resp = requests.get(f"{PLATFORM_API_URL}/api/basket/", headers=get_auth_headers(request), timeout=10)
    except requests.exceptions.ConnectionError:
        return redirect(f'/basket/checkout/?error={quote("Cannot reach the platform API.")}')
    except requests.exceptions.Timeout:
        return redirect(f'/basket/checkout/?error={quote("The platform API took too long to respond.")}')
    except Exception as e:
        return redirect(f'/basket/checkout/?error={quote(str(e))}')

    if basket_resp.status_code == 401:
        request.session.flush()
        return render(request, 'web/login.html', {'error': "Your session has expired. Please log in again."})

    if basket_resp.status_code != 200:
        return redirect(f'/basket/checkout/?error={quote(f"Could not load basket for checkout (status {basket_resp.status_code}).")}')

    basket = basket_resp.json()
    if not basket.get('items'):
        return redirect(f'/basket/checkout/?error={quote("Your basket is empty.")}')

    pending_order_reference = (
        f"pending-{request.session.get('username', 'customer')}-{int(datetime.utcnow().timestamp())}"
    )
    request.session['pending_checkout'] = {
        'delivery_dates': delivery_dates,
        'collection_types': collection_types,
        'delivery_instructions': delivery_instructions,
        'order_reference': pending_order_reference,
        'make_recurring': make_recurring,
        'order_day': order_day,
        'delivery_day': delivery_day,
    }
    request.session.pop('finalized_payment_id', None)
    request.session.pop('finalized_order_id', None)
    request.session.modified = True

    # Fetch current user to get their email and ID
    customer_email = ''
    customer_id = ''
    try:
        user_resp = requests.get(
            f"{PLATFORM_API_URL}/api/auth/me/",
            headers=get_auth_headers(request),
            timeout=5
        )
        if user_resp.status_code == 200:
            user_data = user_resp.json()
            customer_email = user_data.get('email', '')
            customer_id = str(
                user_data.get('id') or user_data.get('user_id') or user_data.get('pk') or ''
            )
    except:
        pass

    checkout_payload = _build_payment_checkout_payload(
        basket=basket,
        pending_order_reference=pending_order_reference,
        customer_email=customer_email,
        customer_id=customer_id,
    )
    checkout_payload['frontend_base_url'] = request.build_absolute_uri('/').rstrip('/')

    try:
        checkout_resp = requests.post(f"{PAYMENT_GATEWAY_URL}/payments/api/checkout/", json=checkout_payload, timeout=10)
    except requests.exceptions.ConnectionError:
        return redirect(f'/basket/checkout/?error={quote("Cannot reach payment service.")}')
    except requests.exceptions.Timeout:
        return redirect(f'/basket/checkout/?error={quote("Payment service timed out.")}')
    except Exception as e:
        return redirect(f'/basket/checkout/?error={quote(str(e))}')

    if checkout_resp.status_code == 200:
        checkout_url = checkout_resp.json().get('url')
        if checkout_url:
            return redirect(checkout_url)
        return redirect(f'/basket/checkout/?error={quote("Stripe checkout did not return a redirect URL.")}')

    gateway_error = _extract_error_from_response(checkout_resp, "Could not start Stripe checkout.")
    return redirect(f'/basket/checkout/?error={quote(f"Payment could not start. {gateway_error}")}')


def reorder(request, order_id):
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': 'Please log in.'})

    if request.method != 'POST':
        return redirect('/orders/')

    try:
        resp = requests.post(
            f"{PLATFORM_API_URL}/api/orders/{order_id}/reorder/",
            headers=get_auth_headers(request),
            timeout=10
        )
    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
        return redirect(f'/orders/?error={quote(error)}')
    except Exception as e:
        error = f"Unexpected error: {str(e)}"
        return redirect(f'/orders/?error={quote(error)}')

    if resp.status_code == 200:
        data = resp.json()
        added = data.get('added', [])
        unavailable = data.get('unavailable', [])

        price_changes = [item for item in added if item.get('price_changed')]

        messages_parts = []
        if added:
            messages_parts.append(f"{len(added)} item(s) added to your basket.")
        if price_changes:
            names = ', '.join(i['product_name'] for i in price_changes)
            messages_parts.append(f"Note: prices have changed for {names}.")
        if unavailable:
            names = ', '.join(i['product_name'] for i in unavailable)
            messages_parts.append(f"Unavailable and skipped: {names}.")

        if not added:
            error = "None of the items from this order are currently available."
            return redirect(f'/orders/?error={quote(error)}')

        success = ' '.join(messages_parts)
        return redirect(f'/basket/?success={quote(success)}')

    error = _extract_error_from_response(resp, "Could not reorder.")
    return redirect(f'/orders/?error={quote(error)}')

def customer_order_history_view(request):
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to place an order."})

    orders = None
    success = None
    recurring_orders = None
    error = request.GET.get('error')
    payment_status = request.GET.get('payment')
    order_id = request.GET.get('order_id')
    payment_id = request.GET.get('payment_id')
    session_id = request.GET.get('session_id')

    if payment_status == 'success':
        pending_checkout = request.session.get('pending_checkout')
        if pending_checkout:
            finalized_order_id, finalize_error = _finalize_pending_order(
                request, payment_id=payment_id, session_id=session_id, order_reference=order_id,
            )
            if finalize_error == AUTH_EXPIRED_ERROR:
                return redirect('/login/')
            if finalized_order_id:
                return redirect(f'/orders/customer/{finalized_order_id}/?payment=success')
            if finalize_error:
                error = finalize_error
            else:
                success = "Payment successful."
        elif order_id and str(order_id).isdigit():
            return redirect(f'/orders/customer/{order_id}/?payment=success')
        else:
            success = "Payment successful."
    elif payment_status == 'cancelled':
        error = "Payment was cancelled. Your basket is unchanged."
        if not request.session.get('payment_failed_notified'):
            request.session['payment_failed_notified'] = True
            customer_id = request.session.get('user_id')
            if customer_id:
                try:
                    user_resp = requests.get(
                        f"{PLATFORM_API_URL}/api/auth/me/",
                        headers=get_auth_headers(request),
                        timeout=5
                    )
                    customer_email = user_resp.json().get('email', '') if user_resp.status_code == 200 else ''
                except Exception:
                    customer_email = ''
                try:
                    requests.post(
                        f"{NOTIFICATIONS_API_URL}/api/notifications/",
                        json={
                            'user':    customer_id,
                            'email':   customer_email,
                            'type':    'PAYMENT_FAILED',
                            'title':   'Payment Unsuccessful',
                            'message': 'Your payment could not be completed. Your basket has not been affected — please try again when you are ready.',
                        },
                        headers={'X-Service-Secret': os.environ.get('NOTIFICATIONS_API_SECRET_KEY', '')},
                        timeout=5,
                    )
                except Exception:
                    pass
    elif payment_status == 'error':
        error = "Payment did not complete."

    total_food_miles = 0

    try:
        resp_orders = requests.get(
            f"{PLATFORM_API_URL}/api/orders/customer-orders/",
            headers=get_auth_headers(request),
            timeout=5
        )
        if resp_orders.status_code == 200:
            orders = resp_orders.json()
            # Food miles stored on each producer order — read directly from DB
            for order in orders:
                order_miles = sum(
                    float(po.get('food_miles') or 0)
                    for po in (order.get('orders') or [])
                    if po.get('food_miles')
                )
                if order_miles:
                    order['food_miles'] = round(order_miles, 1)
                    total_food_miles += order_miles

        elif resp_orders.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load orders (status {resp_orders.status_code})."

        resp_recurring_orders = requests.get(
            f"{PLATFORM_API_URL}/api/orders/recurring/list",
            headers=get_auth_headers(request),
            timeout=5
        )

        if resp_recurring_orders.status_code == 200:
            recurring_orders = resp_recurring_orders.json()
        elif resp_recurring_orders.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load recurring orders (status {resp_recurring_orders.status_code})."
    
    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
    except requests.exceptions.Timeout:
        error = "Request timed out."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/customer_order_history.html', {
        'orders': orders,
        'total_food_miles': round(total_food_miles, 1),
        'recurring_orders': recurring_orders,
        'success': success,
        'error': error,
    })

def recurring_order_detail_view(request, rec_order_id):
    """
    Displays the chosen recurring order's details to the customer.
    """
    if not request.session.get('token'):
        error = "Please log in to view your recurring orders."
        return render(request, 'web/login.html', {
            'error': error,
        })

    rec_order = None
    error = None

    try:
        resp = requests.get(
            f"{PLATFORM_API_URL}/api/orders/recurring/{rec_order_id}/",
            headers=get_auth_headers(request),
            timeout=5
        )
        
        if resp.status_code == 200:
            rec_order = resp.json()
        elif resp.status_code == 404:
            error = "Reccuring order record not found."
        elif resp.status_code == 401:
            error = "Your session has expired. Please log in again."
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load recurring order (status {resp.status_code})."

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
    except requests.exceptions.Timeout:
        error = "Request timed out."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/customer_recurring_order_detail.html', {
        'rec_order': rec_order,
        'error': error,
    })

def recurring_order_update(request, rec_order_id):
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': 'Please log in.'})

    if request.method != 'POST':
        return redirect(f'/orders/recurring/{rec_order_id}/')

    payload = {}
    if 'status' in request.POST:
        payload['status'] = request.POST.get('status')
    if 'order_day' in request.POST:
        payload['order_day'] = request.POST.get('order_day')
    if 'delivery_day' in request.POST:
        payload['delivery_day'] = request.POST.get('delivery_day')

    try:
        resp = requests.patch(
            f"{PLATFORM_API_URL}/api/orders/recurring/{rec_order_id}/update/",
            headers=get_auth_headers(request),
            json=payload,
            timeout=5
        )
        if resp.status_code == 200:
            return redirect(f'/orders/recurring/{rec_order_id}/')
        elif resp.status_code == 404:
            error = "Recurring order not found."
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not update recurring order (status {resp.status_code})."
    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
    except requests.exceptions.Timeout:
        error = "Request timed out."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return redirect(f'/orders/recurring/{rec_order_id}/?error={quote(error)}')

def write_review_view(request, product_id):
    """
    Allow a customer to write a review for a purchased product from a delivered order.
    """
    token = request.session.get('token')
    # Redirect or show error, but we return a general response
    if not token:
        return redirect('login')

    headers = {'Authorization': f'Bearer {token}'}
    platform_api_url = PLATFORM_API_URL

    success = request.GET.get('success')
    error = request.GET.get('error')

    # GET: Form display with product info
    if request.method == 'GET':
        # Fetch the product details to display on the review page
        prod_resp = requests.get(f"{platform_api_url}/api/products/{product_id}/", headers=headers)
        
        if prod_resp.status_code == 200:
            product = prod_resp.json()
        else:
            return redirect(f"/orders/?error=Could not fetch product details.")

        return render(request, 'web/write_review.html', {
            'product': product,
            'media_base_url': platform_api_url,
            'success': success,
            'error': error
        })
        
    # POST: Submit review data
    elif request.method == 'POST':
        rating = request.POST.get('rating')
        title = request.POST.get('title', '')
        comment = request.POST.get('comment', '')
        is_anonymous = request.POST.get('is_anonymous') == 'true'

        payload = {
            'product': product_id,
            'rating': rating,
            'title': title,
            'comment': comment,
            'is_anonymous': is_anonymous
        }

        # Send POST to Platform Service Review endpoint
        review_resp = requests.post(f"{platform_api_url}/api/reviews/", json=payload, headers=headers)
        
        if review_resp.status_code == 201:
            return redirect(f"/products/{product_id}/?success=Your review has been submitted successfully!")
        else:
            try:
                err_data = review_resp.json()
                if isinstance(err_data, list) and len(err_data) > 0:
                    err_msg = err_data[0]
                elif 'non_field_errors' in err_data:
                    err_msg = err_data['non_field_errors'][0]
                else:
                    # Generic dictionary error handling
                    if isinstance(err_data, dict):
                        err_msg = next(iter(err_data.values()))[0] if err_data else "Unknown error"
                    else:
                        err_msg = str(err_data)
            except:
                err_msg = "Could not submit your review. Please try again."

            return redirect(f"/reviews/create/{product_id}/?error=Review error: {err_msg}")

def delete_review_view(request, review_id):
    """
    Allow a customer to delete their previously submitted review.
    """
    headers = get_auth_headers(request)
    if not headers:
        return redirect('login')
    
    product_id = request.POST.get('product_id')
    
    resp = requests.delete(f"{PLATFORM_API_URL}/api/reviews/{review_id}/", headers=headers)
    
    if resp.status_code == 204:
        msg = "Your review has been deleted."
        return redirect(f"/products/{product_id}/?success={msg}") if product_id else redirect('customer-orders')
    else:
        err_msg = "Could not delete review."
        return redirect(f"/products/{product_id}/?error={err_msg}") if product_id else redirect('customer-orders')

def customer_order_detail_view(request, order_id):
    """
    Displays order confirmation and details to the customer after checkout.
    Calculates food miles per producer order based on collection_type.
    """
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to place an order."})

    order = None
    payment_error = request.GET.get('payment_error')
    payment_status = request.GET.get('payment')
    success = "Payment successful." if payment_status == 'success' else None
    error = None

    try:
        resp = requests.get(
            f"{PLATFORM_API_URL}/api/orders/customer-orders/{order_id}/",
            headers=get_auth_headers(request),
            timeout=5
        )
        if resp.status_code == 200:
            order = resp.json()
            # Calculate food miles for DELIVERED delivery orders only

            notif_flag = f'payment_notified_{order_id}'
            if payment_status == 'success' and not request.session.get(notif_flag):
                request.session[notif_flag] = True
                _send_payment_notifications(request, order)

            # Food miles stored on each producer order - just sum them up
            if order.get('orders'):
                total_miles = sum(
                    float(po.get('food_miles') or 0)
                    for po in order['orders']
                    if po.get('food_miles')
                )
                order['total_food_miles'] = round(total_miles, 1)

        elif resp.status_code == 404:
            error = "Order not found."
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load order (status {resp.status_code})."

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
    except requests.exceptions.Timeout:
        error = "Request timed out."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/customer_order_detail.html', {
        'order': order, 'payment_error': payment_error, 'success': success, 'error': error,
    })


def write_review_view(request, product_id):
    token = request.session.get('token')
    if not token:
        return redirect('login')

    headers = {'Authorization': f'Bearer {token}'}
    success = request.GET.get('success')
    error = request.GET.get('error')

    if request.method == 'GET':
        prod_resp = requests.get(f"{PLATFORM_API_URL}/api/products/{product_id}/", headers=headers)
        if prod_resp.status_code == 200:
            product = prod_resp.json()
        else:
            return redirect(f"/orders/?error=Could not fetch product details.")
        return render(request, 'web/write_review.html', {
            'product': product, 'media_base_url': PLATFORM_API_URL, 'success': success, 'error': error
        })

    elif request.method == 'POST':
        payload = {
            'product': product_id,
            'rating': request.POST.get('rating'),
            'title': request.POST.get('title', ''),
            'comment': request.POST.get('comment', ''),
            'is_anonymous': request.POST.get('is_anonymous') == 'true'
        }
        review_resp = requests.post(f"{PLATFORM_API_URL}/api/reviews/", json=payload, headers=headers)
        if review_resp.status_code == 201:
            return redirect(f"/products/{product_id}/?success=Your review has been submitted successfully!")
        else:
            try:
                err_data = review_resp.json()
                if isinstance(err_data, list) and len(err_data) > 0:
                    err_msg = err_data[0]
                elif 'non_field_errors' in err_data:
                    err_msg = err_data['non_field_errors'][0]
                else:
                    err_msg = next(iter(err_data.values()))[0] if isinstance(err_data, dict) and err_data else "Unknown error"
            except:
                err_msg = "Could not submit your review. Please try again."
            return redirect(f"/reviews/create/{product_id}/?error=Review error: {err_msg}")


def delete_review_view(request, review_id):
    headers = get_auth_headers(request)
    if not headers:
        return redirect('login')
    product_id = request.POST.get('product_id')
    resp = requests.delete(f"{PLATFORM_API_URL}/api/reviews/{review_id}/", headers=headers)
    if resp.status_code == 204:
        return redirect(f"/products/{product_id}/?success=Your review has been deleted.") if product_id else redirect('customer-orders')
    else:
        return redirect(f"/products/{product_id}/?error=Could not delete review.") if product_id else redirect('customer-orders')


def producer_orders_view(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    orders = []
    error = None
    total_food_miles = 0
    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/orders/", headers=get_auth_headers(request), timeout=5)
        if resp.status_code == 200:
            orders = resp.json()
            try:
                for order in orders:
                    status = (order.get('status') or '').upper()
                    collection_type = (order.get('collection_type') or '').lower()
                    if status == 'DELIVERED' and 'collect' not in collection_type:
                        items = order.get('items', [])
                        customer_postcode = order.get('customer_postcode')
                        if not customer_postcode and items:
                            customer_postcode = (order.get('customer_profile') or {}).get('postcode')
                        producer_postcode = None
                        if items:
                            product_id = items[0].get('product')
                            if product_id:
                                prod_resp = requests.get(
                                    f"{PLATFORM_API_URL}/api/products/{product_id}/",
                                    headers=get_auth_headers(request),
                                    timeout=5
                                )
                                if prod_resp.status_code == 200:
                                    producer_postcode = (prod_resp.json().get('producer_profile') or {}).get('postcode')
                        if customer_postcode and producer_postcode:
                            miles = _calculate_food_miles(customer_postcode, producer_postcode)
                            if miles:
                                order['food_miles'] = miles
                                total_food_miles += miles
            except Exception:
                pass
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load your orders (status {resp.status_code})."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"
    return render(request, 'web/producer_orders.html', {
        'orders': orders,
        'error': error,
        'total_food_miles': round(total_food_miles, 1),
    })


def producer_order_detail_view(request, order_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    order = None
    error = request.GET.get('error')
    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/orders/{order_id}/", headers=get_auth_headers(request), timeout=5)
        if resp.status_code == 200:
            order = resp.json()
        elif resp.status_code == 404:
            return redirect('/dashboard/orders/')
        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Failed to load order details (status {resp.status_code})."
    except Exception as e:
        error = f"Error communicating with API: {str(e)}"
    return render(request, 'web/producer_order_detail.html', {'order': order, 'error': error})


def producer_update_order_status_view(request, order_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    if request.method == 'POST':
        status_val = request.POST.get('status')
        note = request.POST.get('note', '')
        try:
            resp = requests.patch(
                f"{PLATFORM_API_URL}/api/orders/{order_id}/status/",
                headers=get_auth_headers(request),
                json={'status': status_val, 'note': note},
                timeout=5
            )
            if resp.status_code == 401:
                request.session.flush()
                return redirect('/login/')
            elif resp.status_code != 200:
                try:
                    error_msg = resp.json().get('error', 'Update failed.')
                except:
                    error_msg = "Unknown error occurred."
                from urllib.parse import quote_plus
                return redirect(f'/dashboard/orders/{order_id}/?error={quote_plus(error_msg)}')
        except Exception as e:
            from urllib.parse import quote_plus
            return redirect(f'/dashboard/orders/{order_id}/?error={quote_plus(str(e))}')
    return redirect(f'/dashboard/orders/{order_id}/')


def producer_content_dashboard(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    recipes, stories = [], []
    error = None
    username = request.session.get('username')
    try:
        resp_r = requests.get(f"{PLATFORM_API_URL}/api/products/recipes/", params={'producer__username': username}, timeout=5)
        if resp_r.status_code == 200:
            recipes = resp_r.json()
        resp_s = requests.get(f"{PLATFORM_API_URL}/api/products/farm-stories/", params={'producer__username': username}, timeout=5)
        if resp_s.status_code == 200:
            stories = resp_s.json()
    except Exception as e:
        error = f"Could not load content: {str(e)}"
    return render(request, 'web/content_dashboard.html', {
        'recipes': recipes, 'stories': stories, 'error': error, 'media_base_url': MEDIA_BASE_URL
    })


def add_recipe_view(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    error = None
    products = []
    try:
        resp_p = requests.get(f"{PLATFORM_API_URL}/api/products/", params={'producer__username': request.session.get('username')}, timeout=5)
        if resp_p.status_code == 200:
            products = resp_p.json()
    except:
        pass
    if request.method == 'POST':
        form_data = request.POST.dict()
        form_data.pop('csrfmiddlewaretoken', None)
        files = {}
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            files['image'] = (image_file.name, image_file.read(), image_file.content_type)
        selected_products = request.POST.getlist('products')
        data_tuples = [(k, v) for k, v in form_data.items() if k != 'products']
        for pid in selected_products:
            data_tuples.append(('products', pid))
        try:
            resp = requests.post(
                f"{PLATFORM_API_URL}/api/products/recipes/",
                headers={'Authorization': f"Bearer {request.session.get('token')}"},
                data=data_tuples,
                files=files if files else None,
                timeout=10
            )
            if resp.status_code == 201:
                return redirect('/dashboard/content/')
            else:
                error = f"Failed to create recipe: {resp.text}"
        except Exception as e:
            error = f"Error: {str(e)}"
    return render(request, 'web/add_recipe.html', {'products': products, 'error': error})


def add_farm_story_view(request):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    error = None
    if request.method == 'POST':
        form_data = request.POST.dict()
        form_data.pop('csrfmiddlewaretoken', None)
        files = {}
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            files['image'] = (image_file.name, image_file.read(), image_file.content_type)
        try:
            resp = requests.post(
                f"{PLATFORM_API_URL}/api/products/farm-stories/",
                headers={'Authorization': f"Bearer {request.session.get('token')}"},
                data=form_data,
                files=files if files else None,
                timeout=10
            )
            if resp.status_code == 201:
                return redirect('/dashboard/content/')
            else:
                error = f"Failed to create story: {resp.text}"
        except Exception as e:
            error = f"Error: {str(e)}"
    return render(request, 'web/add_farm_story.html', {'error': error})


def producer_public_profile(request, producer_id):
    profile_data = {}
    error = None
    try:
        resp = requests.get(f"{PLATFORM_API_URL}/api/auth/public-producers/{producer_id}/profile/", timeout=5)
        if resp.status_code == 200:
            profile_data = resp.json()
        elif resp.status_code == 404:
            error = "Producer not found."
        else:
            error = f"Error fetching producer profile (Status {resp.status_code})."
    except Exception as e:
        error = f"Error communicating with API: {str(e)}"
    return render(request, 'web/producer_public_profile.html', {
        'producer': profile_data,
        'products': profile_data.get('products', []),
        'recipes': profile_data.get('recipes', []),
        'stories': profile_data.get('farm_stories', []),
        'error': error,
        'media_base_url': MEDIA_BASE_URL
    })


def delete_recipe_view(request, recipe_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    try:
        requests.delete(
            f"{PLATFORM_API_URL}/api/products/recipes/{recipe_id}/",
            headers={'Authorization': f"Bearer {request.session.get('token')}"},
            timeout=5
        )
    except:
        pass
    return redirect('/dashboard/content/')


def delete_farm_story_view(request, story_id):
    if not request.session.get('token') or request.session.get('role') != 'PRODUCER':
        return redirect('/login/')
    try:
        requests.delete(
            f"{PLATFORM_API_URL}/api/products/farm-stories/{story_id}/",
            headers={'Authorization': f"Bearer {request.session.get('token')}"},
            timeout=5
        )
    except:
        pass
    return redirect('/dashboard/content/')


def notifications_page_view(request):
    if not request.session.get('user_id'):
        return redirect('/login/')
    return render(request, 'web/notifications.html')


def notifications_count_view(request):
    from django.http import JsonResponse
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'unread_count': 0})
    try:
        resp = requests.get(
            f"{NOTIFICATIONS_API_URL}/api/notifications/unread-count/",
            params={'recipient_id': user_id},
            timeout=5
        )
        if resp.status_code == 200:
            return JsonResponse(resp.json())
    except Exception:
        pass
    return JsonResponse({'unread_count': 0})


def notifications_list_view(request):
    from django.http import JsonResponse
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse([], safe=False)
    try:
        resp = requests.get(
            f"{NOTIFICATIONS_API_URL}/api/notifications/list/",
            params={'recipient_id': user_id},
            timeout=5
        )
        if resp.status_code == 200:
            return JsonResponse(resp.json(), safe=False)
    except Exception:
        pass
    return JsonResponse([], safe=False)


def notifications_mark_read_view(request, pk):
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    try:
        resp = requests.patch(
            f"{NOTIFICATIONS_API_URL}/api/notifications/{pk}/",
            json={'recipient_id': user_id},
            timeout=5
        )
        return JsonResponse({'ok': resp.status_code == 200})
    except Exception:
        return JsonResponse({'ok': False})


def notifications_mark_all_read_view(request):
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    try:
        resp = requests.patch(
            f"{NOTIFICATIONS_API_URL}/api/notifications/read-all/",
            json={'recipient_id': user_id},
            timeout=5
        )
        return JsonResponse({'ok': resp.status_code == 200})
    except Exception:
        return JsonResponse({'ok': False})


def admin_notifications_view(request):
    from django.http import JsonResponse
    import os
    if request.session.get('role') != 'ADMIN':
        return JsonResponse({'error': 'Forbidden'}, status=403)
    secret = os.environ.get('NOTIFICATIONS_API_SECRET_KEY', '')
    params = {k: v for k, v in request.GET.items() if k in ('recipient_id', 'type', 'email_sent', 'date_from', 'date_to')}
    try:
        resp = requests.get(
            f"{NOTIFICATIONS_API_URL}/api/notifications/admin/list/",
            params=params,
            headers={'X-Service-Secret': secret},
            timeout=10
        )
        if resp.status_code == 200:
            return JsonResponse(resp.json(), safe=False)
    except Exception:
        pass
    return JsonResponse([], safe=False)


def admin_email_logs_view(request):
    from django.http import JsonResponse
    import os
    if request.session.get('role') != 'ADMIN':
        return JsonResponse({'error': 'Forbidden'}, status=403)
    secret = os.environ.get('NOTIFICATIONS_API_SECRET_KEY', '')
    params = {k: v for k, v in request.GET.items() if k in ('recipient_email', 'type', 'status', 'date_from', 'date_to')}
    try:
        resp = requests.get(
            f"{NOTIFICATIONS_API_URL}/api/notifications/admin/email-logs/",
            params=params,
            headers={'X-Service-Secret': secret},
            timeout=10
        )
        if resp.status_code == 200:
            return JsonResponse(resp.json(), safe=False)
    except Exception:
        pass
    return JsonResponse([], safe=False)


def favourite_toggle_view(request, producer_id):
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    token = request.session.get('token')
    if not token:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    try:
        resp = requests.post(
            f"{PLATFORM_API_URL}/api/auth/favourites/{producer_id}/",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        if resp.status_code in (200, 201):
            return JsonResponse(resp.json())
        return JsonResponse({'error': 'Failed'}, status=resp.status_code)
    except Exception:
        return JsonResponse({'error': 'Service unavailable'}, status=503)


def favourite_list_view(request):
    from django.http import JsonResponse
    token = request.session.get('token')
    if not token:
        return JsonResponse({'favourited_producer_ids': []})
    try:
        resp = requests.get(
            f"{PLATFORM_API_URL}/api/auth/favourites/",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        if resp.status_code == 200:
            return JsonResponse(resp.json())
    except Exception:
        pass
    return JsonResponse({'favourited_producer_ids': []})


def custom_404(request, exception=None):
    return render(request, 'web/404.html', status=404)
