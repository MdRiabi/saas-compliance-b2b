from functools import wraps

from flask import abort
from flask_login import current_user, login_required

ROLES = frozenset({"admin", "compliance", "auditor"})
WRITE_ROLES = frozenset({"admin", "compliance"})


def roles_required(*roles):
    allowed_roles = frozenset(roles)
    if not allowed_roles or not allowed_roles.issubset(ROLES):
        raise ValueError("roles_required must receive one or more valid roles.")

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
