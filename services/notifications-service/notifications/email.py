import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings


def _build_html(title, message, notification_type):
    accent_map = {
        'SURPLUS_DEAL':      '#c85a1e',
        'SEASONAL_REMINDER': '#00622e',
        'ORDER_PLACED':      '#1a7a42',
        'ORDER_CONFIRMED':   '#1a7a42',
        'ORDER_READY':       '#1a7a42',
        'ORDER_DELIVERED':   '#1a7a42',
        'ORDER_CANCELLED':   '#c0392b',
        'LOW_STOCK':         '#e06b2a',
        'OUT_OF_STOCK':      '#c0392b',
        'PAYMENT_RECEIVED':  '#1a7a42',
        'PAYMENT_FAILED':    '#c0392b',
        'ORDER_SUMMARY':     '#1a5276',
    }
    accent = accent_map.get(notification_type, '#00622e')
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;background:#fdf9f3;
                border-radius:8px;overflow:hidden;border:1px solid #e0dbd0;">
        <div style="background:{accent};padding:24px 32px;">
            <h1 style="color:#fff;margin:0;font-size:20px;font-weight:700;">
                Bristol Regional Food Network
            </h1>
        </div>
        <div style="padding:32px;">
            <h2 style="color:#1a1a14;margin:0 0 16px;font-size:18px;">{title}</h2>
            <p style="color:#444;line-height:1.6;margin:0 0 28px;font-size:15px;">{message}</p>
            <a href="http://localhost:8000"
               style="background:{accent};color:#fff;padding:12px 24px;border-radius:6px;
                      text-decoration:none;font-weight:700;font-size:14px;">
                Go to BRFN
            </a>
        </div>
        <div style="padding:16px 32px;background:#f0ebe0;">
            <p style="color:#888;font-size:12px;margin:0;">
                You received this email because you have email notifications enabled.
                You can manage your preferences in your account settings.
            </p>
        </div>
    </div>
    """


def send_notification_email(recipient_email, title, message, notification_type='GENERAL'):
    api_key      = settings.SECURE_ENV.get('BREVO_SECRET_KEY')
    sender_email = settings.SECURE_ENV.get('BREVO_SENDER_EMAIL')
    sender_name  = settings.SECURE_ENV.get('BREVO_SENDER_NAME', 'BRFN Marketplace')

    if not api_key or not sender_email or not recipient_email:
        return

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key

    api = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    subject      = title or notification_type.replace('_', ' ').title()
    html_content = _build_html(subject, message, notification_type)

    email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{'email': recipient_email}],
        sender={'email': sender_email, 'name': sender_name},
        subject=f"BRFN: {subject}",
        html_content=html_content,
    )

    try:
        api.send_transac_email(email)
    except ApiException:
        pass
