"""Dashboard authentication — simple env-var password, no DB hash required."""
import os
from functools import wraps
from flask import session, redirect, url_for, flash

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme-set-admin-password-in-env")


def check_password(password: str) -> bool:
    return password == ADMIN_PASSWORD


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
