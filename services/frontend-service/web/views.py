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
NOTIFICATIONS_API_URL = os.environ.get('NOTIFICATIONS_API_URL', 'http://notifications-api:8001')

def _get_postcode_coords(postcode):
    """Fetch lat/lng for a UK postcode from postcodes.io. Returns (lat, lng) or (None, None)."""
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

def _haversine_miles(lat1, lon1, lat2, lon2):
    """Calculate straight-line distance in miles between two lat/lng points."""
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def _calculate_food_miles(customer_postcode, producer_postcode):
    """Returns distance in miles as a float, or None if postcodes can't be resolved."""
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


def _build_payment_checkout_payload(*, basket, pending_order_reference):
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

    return payload


def _extract_error_from_response(response, default_message):
    try:
        data = response.json()
    except ValueError:
        return default_message
    if isinstance(data, dict):
        return data.get('error') or data.get('detail') or default_message
    return default_message


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
            form_data['delivery_address'] = request.POST.get('delivery_address', '').strip()
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
                    'delivery_address': form_data['delivery_address'],
                    'postcode': form_data['customer_postcode'],
                }
            }
        else:
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

    return render(request, 'web/profile.html', {
        'user': user,
        'error': error,
        'success': success,
    })


def admin_dashboard(request):
    """Admin dashboard with commission monitoring."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')

    headers = get_auth_headers(request)
    users, products, orders = [], [], []
    error = None

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
            # Calculate food miles per DELIVERED delivery order
            for o in orders:
                status = (o.get('status') or '').upper()
                collection_type = (o.get('collection_type') or '').lower()
                if status == 'DELIVERED' and 'collect' not in collection_type:
                    try:
                        items = o.get('items', [])
                        customer_postcode = o.get('customer_postcode') or (o.get('customer_profile') or {}).get('postcode')
                        producer_postcode = None
                        if items:
                            product_id = items[0].get('product')
                            if product_id:
                                prod_resp = requests.get(
                                    f"{PLATFORM_API_URL}/api/products/{product_id}/",
                                    timeout=5
                                )
                                if prod_resp.status_code == 200:
                                    producer_postcode = (prod_resp.json().get('producer_profile') or {}).get('postcode')
                        if customer_postcode and producer_postcode:
                            miles = _calculate_food_miles(customer_postcode, producer_postcode)
                            if miles:
                                o['food_miles'] = miles
                    except Exception:
                        pass

    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API. Please check the service is running."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    total_revenue = sum(float(o.get('total_amount', 0)) for o in orders)
    total_commission = sum(float(o.get('commission_total') or 0) for o in orders)
    total_producer_payout = total_revenue - total_commission
    customers = [u for u in users if u.get('role') == 'CUSTOMER']
    producers = [u for u in users if u.get('role') == 'PRODUCER']

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
            miles = o.get('food_miles')
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

    return render(request, 'web/admin.html', {
        'users': users,
        'products': products,
        'all_orders': orders,
        'error': error,
        'total_revenue': total_revenue,
        'total_commission': total_commission,
        'total_producer_payout': total_producer_payout,
        'producer_breakdown': producer_breakdown_list,
        'customer_count': len(customers),
        'producer_count': len(producers),
        'total_food_miles': round(total_food_miles, 1),
        'producer_food_miles': producer_food_miles_list,
        'media_base_url': MEDIA_BASE_URL,
    })


def admin_commission_export(request):
    """Export commission data as CSV."""
    if not request.session.get('token') or request.session.get('role') != 'ADMIN':
        return redirect('/login/')

    headers = get_auth_headers(request)
    orders = []

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
                'delivery_address': request.POST.get('delivery_address', '').strip(),
                'postcode': request.POST.get('customer_postcode', '').strip(),
            }
        elif role == 'PRODUCER':
            payload['producer_profile'] = {
                'business_name': request.POST.get('business_name', '').strip(),
                'business_address': request.POST.get('business_address', '').strip(),
                'postcode': request.POST.get('producer_postcode', '').strip(),
                'bio': request.POST.get('bio', '').strip(),
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

    return render(request, 'web/dashboard.html', {
        'products': products,
        'error': error,
        'media_base_url': MEDIA_BASE_URL,
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

        for key in ['seasonal_start_month', 'seasonal_end_month', 'harvest_date', 'best_before_date', 'unit', 'allergen_info', 'description']:
            if not form_data.get(key):
                form_data.pop(key, None)

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

        for key in ['seasonal_start_month', 'seasonal_end_month', 'harvest_date', 'best_before_date', 'unit', 'allergen_info', 'description']:
            if not form_data.get(key):
                form_data.pop(key, None)

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
    error = None
    items_by_producer = None

    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to view your basket."})

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
                        customer_postcode = (user_resp.json().get('customer_profile') or {}).get('postcode')
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

    for key, value in request.POST.items():
        if key.startswith('delivery_date_'):
            producer_id = key.replace('delivery_date_', '')
            delivery_dates[producer_id] = value
        elif key.startswith('collection_type_'):
            producer_id = key.replace('collection_type_', '')
            collection_types[producer_id] = value

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
        'order_reference': pending_order_reference,
    }
    request.session.pop('finalized_payment_id', None)
    request.session.pop('finalized_order_id', None)
    request.session.modified = True

    checkout_payload = _build_payment_checkout_payload(basket=basket, pending_order_reference=pending_order_reference)

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


def customer_order_history_view(request):
    if not request.session.get('token'):
        return render(request, 'web/login.html', {'error': "Please log in to place an order."})

    orders = None
    success = None
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
    elif payment_status == 'error':
        error = "Payment did not complete."

    total_food_miles = 0

    try:
        resp = requests.get(
            f"{PLATFORM_API_URL}/api/orders/customer-orders/",
            headers=get_auth_headers(request),
            timeout=5
        )
        if resp.status_code == 200:
            orders = resp.json()
            # Calculate food miles for DELIVERED delivery orders only
            try:
                user_resp = requests.get(
                    f"{PLATFORM_API_URL}/api/auth/me/",
                    headers=get_auth_headers(request),
                    timeout=5
                )
                if user_resp.status_code == 200:
                    customer_postcode = (user_resp.json().get('customer_profile') or {}).get('postcode')
                    if customer_postcode and orders:
                        for order in orders:
                            order_miles = 0
                            for producer_order in (order.get('orders') or []):
                                status = (producer_order.get('status') or '').upper()
                                collection_type = (producer_order.get('collection_type') or '').lower()
                                if status == 'DELIVERED' and 'collect' not in collection_type:
                                    items = producer_order.get('items', [])
                                    if items:
                                        product_id = items[0].get('product')
                                        if product_id:
                                            prod_resp = requests.get(
                                                f"{PLATFORM_API_URL}/api/products/{product_id}/",
                                                timeout=5
                                            )
                                            if prod_resp.status_code == 200:
                                                producer_postcode = (prod_resp.json().get('producer_profile') or {}).get('postcode')
                                                miles = _calculate_food_miles(customer_postcode, producer_postcode)
                                                if miles:
                                                    order_miles += miles
                            if order_miles:
                                order['food_miles'] = round(order_miles, 1)
                                total_food_miles += order_miles
            except Exception:
                pass

        elif resp.status_code == 401:
            request.session.flush()
            return redirect('/login/')
        else:
            error = f"Could not load orders (status {resp.status_code})."
    except requests.exceptions.ConnectionError:
        error = "Cannot reach the platform API."
    except requests.exceptions.Timeout:
        error = "Request timed out."
    except Exception as e:
        error = f"Unexpected error: {str(e)}"

    return render(request, 'web/customer_order_history.html', {
        'orders': orders, 'success': success, 'error': error,
        'total_food_miles': round(total_food_miles, 1),
    })


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

            try:
                user_resp = requests.get(
                    f"{PLATFORM_API_URL}/api/auth/me/",
                    headers=get_auth_headers(request),
                    timeout=5
                )
                if user_resp.status_code == 200:
                    customer_postcode = (user_resp.json().get('customer_profile') or {}).get('postcode')
                    if customer_postcode and order.get('orders'):
                        total_miles = 0
                        for producer_order in order['orders']:
                            collection_type = (producer_order.get('collection_type') or '').lower()
                            if 'collect' in collection_type:
                                producer_order['food_miles'] = 0
                            else:
                                producer_postcode = None
                                items = producer_order.get('items', [])
                                if items:
                                    product_id = items[0].get('product')
                                    if product_id:
                                        prod_resp = requests.get(
                                            f"{PLATFORM_API_URL}/api/products/{product_id}/",
                                            timeout=5
                                        )
                                        if prod_resp.status_code == 200:
                                            producer_postcode = (prod_resp.json().get('producer_profile') or {}).get('postcode')
                                miles = _calculate_food_miles(customer_postcode, producer_postcode) if producer_postcode else None
                                producer_order['food_miles'] = miles
                                if miles:
                                    total_miles += miles
                        order['total_food_miles'] = round(total_miles, 1)
            except Exception:
                pass

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
            # Calculate food miles for DELIVERED delivery orders only
            try:
                for order in orders:
                    status = (order.get('status') or '').upper()
                    collection_type = (order.get('collection_type') or '').lower()
                    if status == 'DELIVERED' and 'collect' not in collection_type:
                        items = order.get('items', [])
                        customer_postcode = order.get('customer_postcode')
                        if not customer_postcode and items:
                            # Try to get customer postcode from order data
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
