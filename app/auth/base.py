from flask import Blueprint
from flask import request
from flask_login import current_user
from app.certificate_auth import get_user_from_cert_subject
from app.auth.views.login_utils import after_login
from app.events.auth_event import LoginEvent
from app.utils import sanitize_next_url
from app.certificate_auth import get_user_from_cert_subject

auth_bp = Blueprint(
    name="auth", import_name=__name__, url_prefix="/auth", template_folder="templates"
)

# … all your existing imports and auth_bp declaration …

@auth_bp.before_request
def cert_auto_login():
    # only intercept the /login endpoint
    if request.endpoint != 'auth.login':
        return

    # if already logged in via session cookie, do nothing
    if current_user.is_authenticated:
        return

    # try to extract client‐cert subject header
    cert_subject = request.headers.get('X-SSL-Client-Subject')
    if not cert_subject:
        return

    # lookup user via certificate helper
    user = get_user_from_cert_subject(cert_subject)
    if not user:
        return

    # on success fire event + hand off to your existing after_login()
    LoginEvent(LoginEvent.ActionType.success).send()
    next_url = sanitize_next_url(request.args.get('next'))
    return after_login(user, next_url)
