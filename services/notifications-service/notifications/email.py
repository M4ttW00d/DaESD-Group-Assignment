import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings


_ACCENT_MAP = {
    'SURPLUS_DEAL':             '#c85a1e',
    'SEASONAL_REMINDER':        '#00622e',
    'ORDER_PLACED':             '#1a7a42',
    'ORDER_CONFIRMED':          '#1a7a42',
    'ORDER_READY':              '#1a7a42',
    'ORDER_DELIVERED':          '#1a7a42',
    'ORDER_CANCELLED':          '#c0392b',
    'ORDER_UPDATE':             '#1a7a42',
    'LOW_STOCK':                '#e06b2a',
    'OUT_OF_STOCK':             '#c0392b',
    'PAYMENT_RECEIVED':         '#1a7a42',
    'PAYMENT_FAILED':           '#c0392b',
    'ORDER_SUMMARY':            '#1a7a42',
    'SETTLEMENT_READY':         '#1a7a42',
    'RECURRING_ORDER_REMINDER': '#7d3c98',
    'RECURRING_ORDER_PLACED':   '#1a7a42',
    'RECURRING_ORDER_PAUSED':   '#c0392b',
}


def _build_html(title, message, notification_type):
    accent   = _ACCENT_MAP.get(notification_type, '#00622e')
    site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')

    html_lines = []
    for raw in message.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        esc = raw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        stripped = esc.strip()
        if not stripped:
            html_lines.append('<div style="height:6px;"></div>')
        elif stripped.startswith('•'):
            html_lines.append(
                f'<div style="color:#444;font-size:14px;line-height:1.7;padding:1px 0 1px 16px;">'
                f'{stripped}</div>'
            )
        else:
            html_lines.append(
                f'<div style="color:#444;font-size:14px;line-height:1.7;padding:1px 0;">'
                f'{esc}</div>'
            )
    body_html = '\n'.join(html_lines)

    return f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;background:#fdf9f3;
            border-radius:8px;overflow:hidden;border:1px solid #e0dbd0;">

    <div style="background:{accent};padding:20px 32px;">
        <div style="color:#fff;font-size:17px;font-weight:700;
                    letter-spacing:0.01em;line-height:1.2;">
            Bristol Regional Food Network
        </div>
        <div style="color:rgba(255,255,255,0.75);font-size:11px;
                    margin-top:3px;letter-spacing:0.03em;">
            Farm to fork &middot; Bristol
        </div>
    </div>

    <div style="padding:32px;">
        <h2 style="color:#1a1a14;margin:0 0 20px;font-size:18px;font-weight:700;">
            {title}
        </h2>
        <div style="margin:0 0 28px;">
            {body_html}
        </div>
        <a href="{site_url}"
           style="display:inline-block;background:{accent};color:#fff;
                  padding:12px 24px;border-radius:6px;text-decoration:none;
                  font-weight:700;font-size:14px;">
            Visit BRFN
        </a>
    </div>

    <div style="padding:16px 32px;background:#f0ebe0;border-top:1px solid #e0dbd0;">
        <p style="color:#888;font-size:12px;margin:0;line-height:1.6;">
            You received this email because you have email notifications enabled
            on your Bristol Regional Food Network account.
            You can manage your preferences in your
            <a href="{site_url}/profile/" style="color:#00622e;text-decoration:none;">
                account settings</a>.
        </p>
    </div>

</div>
"""


def send_notification_email(recipient_email, title, message, notification_type='GENERAL'):
    api_key      = settings.SECURE_ENV.get('BREVO_SECRET_KEY')
    sender_email = settings.SECURE_ENV.get('BREVO_SENDER_EMAIL')
    sender_name  = settings.SECURE_ENV.get('BREVO_SENDER_NAME', 'BRFN Marketplace')

    subject      = title or notification_type.replace('_', ' ').title()
    full_subject = f"BRFN: {subject}"
    html_content = _build_html(subject, message, notification_type)

    if not api_key or not sender_email or not recipient_email:
        return False, full_subject, html_content, 'Missing credentials or recipient'

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key

    api = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{'email': recipient_email}],
        sender={'email': sender_email, 'name': sender_name},
        subject=full_subject,
        html_content=html_content,
    )

    try:
        api.send_transac_email(email)
        return True, full_subject, html_content, ''
    except ApiException as e:
        return False, full_subject, html_content, str(e)
