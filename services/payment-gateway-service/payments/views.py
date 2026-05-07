import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

try:
    import stripe
except ModuleNotFoundError:
    stripe = None

from django.conf import settings
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import Payment, ProducerSettlement, WeeklySettlement


class CheckoutError(Exception):
    """Raised when the incoming order payload is not usable for checkout."""


@csrf_exempt
def create_checkout(request):
    """Create a Stripe-hosted checkout session from an order JSON payload."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        _require_stripe()
        payload = _parse_request_payload(request)
        session, payment = _create_checkout_session(request=request, payload=payload)
        return JsonResponse(
            {
                'url': session.url,
                'session_id': session.id,
                'payment_id': payment.id,
                'order_id': payment.order_id,
            }
        )
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Request body must be valid JSON.'}, status=400)
    except stripe.error.RateLimitError:
        return JsonResponse({'error': 'Stripe rate limit hit'}, status=400)
    except stripe.error.InvalidRequestError as exc:
        return JsonResponse({'error': f'Invalid Stripe request: {exc}'}, status=400)
    except stripe.error.AuthenticationError:
        return JsonResponse({'error': 'Stripe authentication failed'}, status=401)
    except stripe.error.APIConnectionError:
        return JsonResponse({'error': 'Stripe API connection failed'}, status=503)
    except stripe.error.StripeError as exc:
        return JsonResponse({'error': f'Stripe error: {exc}'}, status=400)
    except Exception as exc:
        return JsonResponse({'error': f'Unexpected error: {exc}'}, status=500)


def list_transactions(request):
    """List recent Stripe checkout transactions for admin reporting."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    try:
        _require_stripe()
        if not _stripe_is_configured():
            raise CheckoutError('Add your Stripe test keys to the environment before fetching transactions.')

        stripe.api_key = settings.STRIPE_SECRET_KEY
        limit = _coerce_limit(request.GET.get('limit'))

        sessions = stripe.checkout.Session.list(
            limit=limit,
            expand=['data.payment_intent.latest_charge'],
        )
        session_rows = sessions.data
        session_ids = [s.id for s in session_rows if s.id]

        payments_by_session = {
            p.stripe_session_id: p
            for p in Payment.objects.filter(stripe_session_id__in=session_ids)
        }

        transactions = []
        for session in session_rows:
            session_id = session.id
            local_payment = payments_by_session.get(session_id)
            amount_total = session.amount_total
            created_unix = session.created
            payment_status = session.payment_status or 'unknown'

            # session.metadata is a StripeObject in newer sdk versions – avoid calling
            # .get() on it directly as StripeObject may not support dict-style .get().
            metadata_order_id = ''
            metadata_user_id = ''
            if session.metadata:
                try:
                    metadata_order_id = session.metadata['order_id'] or ''
                except (KeyError, TypeError, AttributeError):
                    pass
                try:
                    metadata_user_id = session.metadata['user_id'] or ''
                except (KeyError, TypeError, AttributeError):
                    pass

            # Try to get user_id from local payment request_payload first, then metadata
            user_id = ''
            if local_payment:
                try:
                    payload = local_payment.request_payload or {}
                    user_id = str(payload.get('user_id') or '')
                except (TypeError, AttributeError):
                    pass
            if not user_id:
                user_id = metadata_user_id

            # Try to get email from Stripe session first, then from local payment request payload
            customer_email = session.customer_email or ''
            if not customer_email and local_payment:
                try:
                    payload = local_payment.request_payload or {}
                    customer_email = payload.get('customer_email') or ''
                except (TypeError, AttributeError):
                    pass

            # payment_intent may be either an id string or an expanded PaymentIntent.
            payment_intent_val = session.payment_intent
            payment_intent_str = (
                str(payment_intent_val)
                if payment_intent_val and not isinstance(payment_intent_val, str)
                else (payment_intent_val or '')
            )

            stripe_refunded = False
            latest_charge = None
            if payment_intent_val and not isinstance(payment_intent_val, str):
                latest_charge = getattr(payment_intent_val, 'latest_charge', None)
            if latest_charge:
                amount_refunded = 0
                refunded_flag = False
                try:
                    amount_refunded = int(latest_charge['amount_refunded'] or 0)
                except (KeyError, TypeError, ValueError, AttributeError):
                    pass
                try:
                    refunded_flag = bool(latest_charge['refunded'])
                except (KeyError, TypeError, AttributeError):
                    pass
                stripe_refunded = refunded_flag or amount_refunded > 0

            if stripe_refunded:
                display_status = 'REFUNDED'
                if local_payment and local_payment.status != 'REFUNDED':
                    local_payment.status = 'REFUNDED'
                    local_payment.save(update_fields=['status', 'updated_at'])
            else:
                display_status = 'REFUNDED' if local_payment and local_payment.status == 'REFUNDED' else payment_status

            transactions.append(
                {
                    'session_id': session_id,
                    'order_id': (local_payment.order_id if local_payment else '') or metadata_order_id or '',
                    'user_id': user_id,
                    'customer_email': customer_email,
                    'amount_total': _format_amount(amount_total),
                    'currency': (session.currency or '').upper(),
                    'payment_status': payment_status,
                    'display_status': display_status,
                    'status': local_payment.status if local_payment else '',
                    'created_at': _format_unix(created_unix),
                    'payment_intent': payment_intent_str,
                    'url': str(session.url or ''),
                }
            )

        return JsonResponse({'transactions': transactions})
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except stripe.error.AuthenticationError:
        return JsonResponse({'error': 'Stripe authentication failed'}, status=401)
    except stripe.error.APIConnectionError:
        return JsonResponse({'error': 'Stripe API connection failed'}, status=503)
    except stripe.error.StripeError as exc:
        return JsonResponse({'error': f'Stripe error: {exc}'}, status=400)
    except Exception as exc:
        logger.exception('Unexpected error in list_transactions')
        return JsonResponse({'error': f'Unexpected error: {type(exc).__name__}: {exc}'}, status=500)


def list_unsettled_payments(request):
    """Return successful local Payment records that have not yet been included in a settlement."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    payments = Payment.objects.filter(status='SUCCESS', settled=False)
    return JsonResponse({'payments': [
        {
            'payment_id': p.id,
            'order_id': p.order_id,
            'amount': str(p.amount),
            'currency': p.currency,
            'stripe_session_id': p.stripe_session_id or '',
            'created_at': p.created_at.isoformat(),
        }
        for p in payments
    ]})


@csrf_exempt
def run_settlement(request):
    """Receive compiled per-producer settlement data, record it and attempt Stripe transfers."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    payment_ids = body.get('payment_ids') or []
    producers_data = body.get('producers') or []

    if not producers_data:
        return JsonResponse({'error': 'No producers provided'}, status=400)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday of current week
    total_amount = sum(Decimal(str(p.get('amount', '0') or '0')) for p in producers_data)

    settlement = WeeklySettlement.objects.create(
        week_start=week_start,
        week_end=today,
        total_amount=total_amount,
        status='PENDING',
    )

    producer_records = []
    for p in producers_data:
        amount = Decimal(str(p.get('amount', '0') or '0'))
        stripe_account_id = (p.get('stripe_account_id') or '').strip()
        transfer_id = ''
        status = 'PENDING'
        error_message = ''

        if not stripe_account_id:
            status = 'SKIPPED'
            error_message = 'No Stripe connected account ID set for this producer'
        elif not _stripe_is_configured():
            status = 'SKIPPED'
            error_message = 'Stripe secret key not configured'
        else:
            try:
                _require_stripe()
                stripe.api_key = settings.STRIPE_SECRET_KEY
                transfer = stripe.Transfer.create(
                    amount=int(amount * 100),  # convert to pence
                    currency='gbp',
                    destination=stripe_account_id,
                    description=f'BRFN weekly settlement {week_start} to {today}',
                    metadata={
                        'settlement_id': str(settlement.id),
                        'producer_id': str(p.get('producer_id', '')),
                        'producer_name': p.get('producer_name', ''),
                    },
                )
                transfer_id = transfer.id
                status = 'TRANSFERRED'
            except Exception as exc:
                error_message = str(exc)
                status = 'FAILED'

        ps = ProducerSettlement.objects.create(
            settlement=settlement,
            producer_id=str(p.get('producer_id', '')),
            producer_name=p.get('producer_name', ''),
            stripe_account_id=stripe_account_id,
            amount=amount,
            transfer_id=transfer_id,
            status=status,
            error_message=error_message,
        )
        producer_records.append(ps)

    # Mark payments as settled
    if payment_ids:
        Payment.objects.filter(pk__in=payment_ids).update(settled=True)

    # Update overall settlement status
    statuses = {ps.status for ps in producer_records}
    if all(s in ('TRANSFERRED', 'SKIPPED') for s in statuses):
        settlement.status = 'COMPLETED'
    elif any(s == 'FAILED' for s in statuses):
        settlement.status = 'FAILED'
    else:
        settlement.status = 'COMPLETED'
    settlement.save(update_fields=['status'])

    return JsonResponse({
        'settlement_id': settlement.id,
        'status': settlement.status,
        'total_amount': str(settlement.total_amount),
        'producer_count': len(producer_records),
        'producers': [
            {
                'producer_id': ps.producer_id,
                'producer_name': ps.producer_name,
                'amount': str(ps.amount),
                'status': ps.status,
                'transfer_id': ps.transfer_id,
                'error_message': ps.error_message,
            }
            for ps in producer_records
        ],
    })


def list_settlements(request):
    """List all recorded weekly settlements."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    settlements = (
        WeeklySettlement.objects
        .prefetch_related('producer_settlements')
        .order_by('-created_at')
    )
    return JsonResponse({'settlements': [
        {
            'id': s.id,
            'week_start': str(s.week_start),
            'week_end': str(s.week_end),
            'total_amount': str(s.total_amount),
            'status': s.status,
            'created_at': s.created_at.isoformat(),
            'producers': [
                {
                    'producer_id': ps.producer_id,
                    'producer_name': ps.producer_name,
                    'amount': str(ps.amount),
                    'status': ps.status,
                    'transfer_id': ps.transfer_id,
                    'error_message': ps.error_message,
                }
                for ps in s.producer_settlements.all()
            ],
        }
        for s in settlements
    ]})


@csrf_exempt
def update_payment_order_reference(request):
    """Update a successful payment record to point at the final customer order id."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    final_order_id = str(body.get('order_id') or '').strip()
    payment_id = str(body.get('payment_id') or '').strip()
    session_id = str(body.get('session_id') or '').strip()

    if not final_order_id:
        return JsonResponse({'error': 'order_id is required'}, status=400)
    if not payment_id and not session_id:
        return JsonResponse({'error': 'payment_id or session_id is required'}, status=400)

    queryset = Payment.objects.all()
    if payment_id:
        queryset = queryset.filter(pk=payment_id)
    if session_id:
        queryset = queryset.filter(stripe_session_id=session_id)

    payment = queryset.first()
    if not payment:
        return JsonResponse({'error': 'Payment not found'}, status=404)

    payment.order_id = final_order_id
    payment.save(update_fields=['order_id', 'updated_at'])
    return JsonResponse({
        'updated': True,
        'payment_id': payment.id,
        'order_id': payment.order_id,
    })


@csrf_exempt
def refund_by_order(request):
    """Issue a Stripe refund for the payment tied to a given order_id.

    POST /payments/api/refund/
    Body: {"order_id": "<CustomerOrder.id>"}

    The link between orders and payments:
      - When a customer checks out, the frontend sends CustomerOrder.id as order_id
        to the payment gateway's /payments/api/checkout/ endpoint.
      - The gateway stores it as Payment.order_id (a string of the integer PK).
      - So to refund, we look up Payment where order_id = str(customer_order_id)
        and status = SUCCESS, then call stripe.Refund.create(payment_intent=...).
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = str(body.get('order_id') or '').strip()
    payment_id = str(body.get('payment_id') or '').strip()
    if not order_id and not payment_id:
        return JsonResponse({'error': 'order_id or payment_id is required'}, status=400)

    payment = None
    if order_id:
        payment = Payment.objects.filter(order_id=order_id, status='SUCCESS').first()
    if not payment and payment_id:
        payment = Payment.objects.filter(pk=payment_id, status='SUCCESS').first()
    if not payment:
        reference = order_id or payment_id
        return JsonResponse({'error': f'No successful payment found for reference {reference}'}, status=404)

    if not payment.stripe_payment_intent:
        return JsonResponse({'error': 'Payment has no Stripe payment intent — cannot refund'}, status=400)

    if not _stripe_is_configured():
        return JsonResponse({'error': 'Stripe is not configured on this server'}, status=503)

    try:
        _require_stripe()
        stripe.api_key = settings.STRIPE_SECRET_KEY
        refund = stripe.Refund.create(
            payment_intent=payment.stripe_payment_intent,
            metadata={
                'order_id': order_id or payment.order_id,
                'payment_id': str(payment.id),
                'reason': 'order_cancellation',
            },
        )
        payment.status = 'REFUNDED'
        payment.save(update_fields=['status', 'updated_at'])
        return JsonResponse({
            'refunded': True,
            'refund_id': refund.id,
            'amount': str(payment.amount),
            'currency': payment.currency,
        })
    except stripe.error.InvalidRequestError as exc:
        return JsonResponse({'error': f'Stripe error: {exc}'}, status=400)
    except stripe.error.StripeError as exc:
        return JsonResponse({'error': f'Stripe error: {exc}'}, status=400)
    except Exception as exc:
        logger.exception('Unexpected error in refund_by_order')
        return JsonResponse({'error': f'Unexpected error: {exc}'}, status=500)


def payment_status(request):
    """Return the local payment status for a payment/session pair."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    payment_id = request.GET.get('payment_id')
    session_id = request.GET.get('session_id')

    if not payment_id and not session_id:
        return JsonResponse({'error': 'Provide payment_id or session_id.'}, status=400)

    queryset = Payment.objects.all()
    if payment_id:
        queryset = queryset.filter(pk=payment_id)
    if session_id:
        queryset = queryset.filter(stripe_session_id=session_id)

    payment = queryset.first()
    if not payment:
        return JsonResponse({'error': 'Payment not found.'}, status=404)

    return JsonResponse(
        {
            'payment_id': payment.id,
            'order_id': payment.order_id,
            'session_id': payment.stripe_session_id,
            'status': payment.status,
            'currency': payment.currency,
            'amount': str(payment.amount),
        }
    )


def checkout_success(request):
    """Verify Stripe success, then redirect to frontend homepage with a success flag."""
    payment = _get_payment_from_request(request)
    session_id = request.GET.get('session_id')
    message = 'Stripe confirmed the checkout and the payment record has been updated.'
    checkout_paid = False

    if session_id and _stripe_is_configured():
        _require_stripe()
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.InvalidRequestError:
            message = 'Payment completed, but the returned session id was invalid. Check success_url token formatting.'
        else:
            if not payment:
                payment = Payment.objects.filter(stripe_session_id=session_id).first()
            if payment:
                payment_status = session.payment_status
                payment_intent_id = session.payment_intent
                update_fields = []
                if payment_intent_id and payment.stripe_payment_intent != payment_intent_id:
                    payment.stripe_payment_intent = payment_intent_id
                    update_fields.append('stripe_payment_intent')

                if payment_status == 'paid':
                    checkout_paid = True
                    payment.status = 'SUCCESS'
                    update_fields.append('status')
                elif payment_intent_id and _payment_intent_failed(payment_intent_id):
                    payment.status = 'FAILED'
                    update_fields.append('status')
                    message = 'Stripe marked this payment as failed.'
                else:
                    message = 'Checkout returned, but Stripe has not marked this session as paid yet.'

                if update_fields:
                    payment.save(update_fields=list(set(update_fields + ['updated_at'])))

    if checkout_paid and payment:
        return redirect(_frontend_success_redirect_url(payment=payment))

    return render(
        request,
        'payments/result.html',
        {
            'payment': payment,
            'heading': 'Payment successful',
            'message': message,
            'is_success': True,
        },
    )


def checkout_cancel(request):
    """Show a simple cancel page when the hosted checkout is abandoned."""
    payment = _get_payment_from_request(request)
    session_id = request.GET.get('session_id')

    if not payment and session_id:
        payment = Payment.objects.filter(stripe_session_id=session_id).first()
    if payment and payment.status == 'PENDING':
        payment.status = 'CANCELLED'
        payment.save(update_fields=['status', 'updated_at'])

    return redirect(_frontend_cancel_redirect_url(payment=payment))


@csrf_exempt
def webhook(request):
    """Handle Stripe webhook events when a webhook secret is configured."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not settings.STRIPE_WEBHOOK_SECRET:
        return JsonResponse({'error': 'STRIPE_WEBHOOK_SECRET is not configured.'}, status=400)

    _require_stripe()
    stripe.api_key = settings.STRIPE_SECRET_KEY
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError:
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        payment = Payment.objects.filter(stripe_session_id=session['id']).first()
        if payment:
            update_fields = []
            payment_intent_id = session.get('payment_intent')
            if payment_intent_id and payment.stripe_payment_intent != payment_intent_id:
                payment.stripe_payment_intent = payment_intent_id
                update_fields.append('stripe_payment_intent')

            if session.get('payment_status') == 'paid':
                payment.status = 'SUCCESS'
                update_fields.append('status')

            if update_fields:
                payment.save(update_fields=list(set(update_fields + ['updated_at'])))

    if event['type'] == 'checkout.session.expired':
        session = event['data']['object']
        payment = Payment.objects.filter(stripe_session_id=session['id']).first()
        if payment and payment.status == 'PENDING':
            payment.status = 'FAILED'
            payment.save(update_fields=['status', 'updated_at'])

    if event['type'] == 'checkout.session.async_payment_failed':
        session = event['data']['object']
        payment = Payment.objects.filter(stripe_session_id=session['id']).first()
        if payment:
            update_fields = []
            payment_intent_id = session.get('payment_intent')
            if payment_intent_id and payment.stripe_payment_intent != payment_intent_id:
                payment.stripe_payment_intent = payment_intent_id
                update_fields.append('stripe_payment_intent')
            if payment.status != 'FAILED':
                payment.status = 'FAILED'
                update_fields.append('status')
            if update_fields:
                payment.save(update_fields=list(set(update_fields + ['updated_at'])))

    if event['type'] == 'payment_intent.payment_failed':
        intent = event['data']['object']
        metadata = intent.get('metadata') or {}
        payment = None

        payment_intent_id = intent.get('id')
        if payment_intent_id:
            payment = Payment.objects.filter(stripe_payment_intent=payment_intent_id).first()

        if not payment and metadata.get('payment_id'):
            payment = Payment.objects.filter(pk=metadata.get('payment_id')).first()

        if payment:
            payment.status = 'FAILED'
            if payment_intent_id:
                payment.stripe_payment_intent = payment_intent_id
                payment.save(update_fields=['status', 'stripe_payment_intent', 'updated_at'])
            else:
                payment.save(update_fields=['status', 'updated_at'])

    return JsonResponse({'status': 'received'})


def _parse_request_payload(request):
    if request.content_type and 'application/json' in request.content_type:
        return json.loads(request.body.decode('utf-8') or '{}')
    return {}


def _create_checkout_session(*, request, payload):
    _require_stripe()
    if not _stripe_is_configured():
        raise CheckoutError('Add your Stripe test keys to the environment before starting checkout.')

    checkout_data = _build_checkout_data(payload)

    payment = Payment.objects.create(
        order_id=checkout_data['order_id'],
        amount=checkout_data['amount'],
        currency=checkout_data['currency'],
        status='PENDING',
        request_payload=payload,
    )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    session_kwargs = {
        'mode': 'payment',
        'payment_method_types': ['card'],
        'line_items': checkout_data['line_items'],
        'metadata': {
            'payment_id': str(payment.id),
            'order_id': checkout_data['order_id'],
            'user_id': checkout_data.get('user_id', ''),
        },
        'payment_intent_data': {
            'metadata': {
                'payment_id': str(payment.id),
                'order_id': checkout_data['order_id'],
                'user_id': checkout_data.get('user_id', ''),
            }
        },
        'success_url': checkout_data['success_url'] or _default_success_url(request, payment.id),
        'cancel_url': checkout_data['cancel_url'] or _default_cancel_url(request, payment.id),
    }
    if checkout_data['customer_email']:
        session_kwargs['customer_email'] = checkout_data['customer_email']

    session = stripe.checkout.Session.create(**session_kwargs)
    payment.stripe_session_id = session.id
    payment.save(update_fields=['stripe_session_id', 'updated_at'])
    return session, payment


def _build_checkout_data(payload):
    if not isinstance(payload, dict) or not payload:
        raise CheckoutError('Send a JSON object containing the order details.')

    order = payload.get('order') if isinstance(payload.get('order'), dict) else payload
    items = payload.get('items') or order.get('items') or []
    order_id = str(payload.get('order_id') or order.get('order_id') or order.get('id') or '')
    currency = str(payload.get('currency') or order.get('currency') or settings.STRIPE_CURRENCY).lower()
    customer_email = payload.get('customer_email') or order.get('customer_email') or order.get('email')
    user_id = str(payload.get('user_id') or order.get('user_id') or '')

    if items:
        line_items, amount = _build_line_items(items=items, currency=currency, order_id=order_id)
    else:
        amount = _coerce_decimal(
            payload.get('total_amount') or order.get('total_amount'),
            field_name='total_amount',
        )
        line_items = [
            {
                'price_data': {
                    'currency': currency,
                    'unit_amount': _decimal_to_cents(amount),
                    'product_data': {
                        'name': payload.get('title') or f'Order #{order_id or "payment"}',
                        'description': payload.get('description') or 'Regional Food Network checkout',
                    },
                },
                'quantity': 1,
            }
        ]

    return {
        'amount': amount,
        'currency': currency,
        'customer_email': customer_email,
        'user_id': user_id,
        'line_items': line_items,
        'order_id': order_id,
        'success_url': payload.get('success_url'),
        'cancel_url': payload.get('cancel_url'),
    }


def _build_line_items(*, items, currency, order_id):
    line_items = []
    total_amount = Decimal('0.00')

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise CheckoutError('Each item in items must be a JSON object.')

        quantity = _coerce_quantity(item.get('quantity', 1))
        unit_price = _coerce_item_price(item)
        product_name = item.get('name') or item.get('product_name') or item.get('title') or f'Order {order_id or ""} item {index}'.strip()

        product_data = {'name': product_name}
        description = item.get('description')
        if description:
            product_data['description'] = description

        image_url = item.get('image_url') or item.get('image')
        if image_url:
            product_data['images'] = [image_url]

        line_items.append(
            {
                'price_data': {
                    'currency': currency,
                    'unit_amount': _decimal_to_cents(unit_price),
                    'product_data': product_data,
                },
                'quantity': quantity,
            }
        )
        total_amount += unit_price * quantity

    if not line_items:
        raise CheckoutError('At least one order item is required.')

    return line_items, total_amount


def _coerce_item_price(item):
    if item.get('unit_amount') not in (None, ''):
        try:
            unit_amount = int(item['unit_amount'])
        except (TypeError, ValueError) as exc:
            raise CheckoutError('unit_amount must be an integer amount in pence.') from exc
        if unit_amount < 1:
            raise CheckoutError('unit_amount must be greater than zero.')
        return (Decimal(unit_amount) / Decimal('100')).quantize(Decimal('0.01'))

    for field_name in ('price_at_sale', 'unit_price', 'price', 'amount'):
        if item.get(field_name) not in (None, ''):
            return _coerce_decimal(item[field_name], field_name=field_name)

    raise CheckoutError('Each order item must include unit_amount or a price field.')


def _coerce_decimal(value, *, field_name):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CheckoutError(f'{field_name} must be a valid amount.') from exc

    if amount <= 0:
        raise CheckoutError(f'{field_name} must be greater than zero.')
    return amount.quantize(Decimal('0.01'))


def _coerce_quantity(value):
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise CheckoutError('quantity must be a whole number.') from exc

    if quantity < 1:
        raise CheckoutError('quantity must be at least 1.')
    return quantity


def _decimal_to_cents(value):
    return int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _default_success_url(request, payment_id):
    gateway_base = (settings.PAYMENT_GATEWAY_URL or '').rstrip('/')
    if not gateway_base:
        gateway_base = f"{request.scheme}://{request.get_host()}"
    return (
        f"{gateway_base}{reverse('payments:success')}"
        f"?payment_id={payment_id}&session_id={{CHECKOUT_SESSION_ID}}"
    )


def _default_cancel_url(request, payment_id):
    gateway_base = (settings.PAYMENT_GATEWAY_URL or '').rstrip('/')
    if not gateway_base:
        gateway_base = f"{request.scheme}://{request.get_host()}"
    return (
        f"{gateway_base}{reverse('payments:cancel')}"
        f"?payment_id={payment_id}"
    )


def _frontend_success_redirect_url(*, payment):
    frontend_base = _resolve_frontend_base_url(payment=payment)
    query = {
        'payment': 'success',
        'payment_id': payment.id,
    }
    if payment.stripe_session_id:
        query['session_id'] = payment.stripe_session_id
    order_id = str(payment.order_id or '').strip()
    if order_id:
        query['order_id'] = order_id
    return f'{frontend_base}/orders/?{urlencode(query)}'


def _frontend_cancel_redirect_url(*, payment=None):
    frontend_base = _resolve_frontend_base_url(payment=payment)
    query = {
        'payment': 'cancelled',
        'error': 'Payment was cancelled. Your basket has not been placed.',
    }
    if payment:
        query['payment_id'] = payment.id
        if payment.stripe_session_id:
            query['session_id'] = payment.stripe_session_id
        order_id = str(payment.order_id or '').strip()
        if order_id:
            query['order_id'] = order_id
    return f'{frontend_base}/basket/checkout/?{urlencode(query)}'


def _coerce_limit(value):
    default_limit = 50
    max_limit = 100
    if value in (None, ''):
        return default_limit
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default_limit
    if parsed < 1:
        return default_limit
    return min(parsed, max_limit)


def _resolve_frontend_base_url(*, payment=None):
    if payment:
        try:
            payload = payment.request_payload or {}
            frontend_from_payload = str(payload.get('frontend_base_url') or '').rstrip('/')
            if frontend_from_payload:
                return frontend_from_payload
        except (TypeError, AttributeError):
            pass

    return (settings.FRONTEND_URL or 'http://localhost:8000').rstrip('/')


def _format_amount(value):
    if value in (None, ''):
        return ''
    return str((Decimal(value) / Decimal('100')).quantize(Decimal('0.01')))


def _format_unix(value):
    if value in (None, ''):
        return ''
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ''
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _get_payment_from_request(request):
    payment_id = request.GET.get('payment_id')
    if not payment_id:
        return None
    return Payment.objects.filter(pk=payment_id).first()


def _stripe_is_configured():
    secret_key = settings.STRIPE_SECRET_KEY or ''
    return secret_key.startswith('sk_') and 'FILL_ME_IN' not in secret_key


def _require_stripe():
    if stripe is None:
        raise CheckoutError('Stripe is not installed. Install the payment service requirements first.')


def _payment_intent_failed(payment_intent_id):
    """
    True only when Stripe marks the PaymentIntent in a failure state.
    """
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError:
        return False
    return intent.status in {'requires_payment_method', 'canceled'}
