# This file is only an example to get you started - please delete once the Brevo email service is integrated.

import sib_api_v3_sdk
import os

from sib_api_v3_sdk.rest import ApiException

def load_env_file():
    # Build path relative to this script file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, '.env.secure')
    
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        print(f"Warning: .env.secure not found at {path}")
    return env
env = load_env_file()

# Replace needed fields below in the .env.secure file with the correct emails and key for testing.
API_KEY = env.get('BREVO_SECRET_KEY')
SENDER_EMAIL = env.get('BREVO_SENDER_EMAIL')
SENDER_NAME = "BRFN Marketplace"
TO_EMAIL = env.get('BREVO_RECIPIENT_EMAIL')
TO_NAME = "Your Name"

configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = API_KEY

api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

email = sib_api_v3_sdk.SendSmtpEmail(
    to=[{"email": TO_EMAIL, "name": TO_NAME}],
    sender={"email": SENDER_EMAIL, "name": SENDER_NAME},
    subject="Test Email from Brevo",
    html_content="<h1>It works!</h1><p>This is a test email sent via Brevo.</p>"
)

try:
    response = api.send_transac_email(email)
    print("Email sent successfully:", response)
except ApiException as e:
    print("Error sending email:", e)