"""Web dashboard — runs alongside the Telegram bot."""
import os
from flask import Flask, render_template, request, redirect, url_for, session
from config import Config
from dashboard_app.auth import check_password, login_required
from dashboard_app.routes import bp as dashboard_bp
from models import migrate_db

migrate_db()

app = Flask(__name__, template_folder="dashboard_app/templates")
app.secret_key = Config.SECRET_KEY
app.register_blueprint(dashboard_bp)


@app.context_processor
def inject_branding():
    """Make APP_NAME and COMPANY_NAME available to all templates without needing to pass them from every route."""
    return {
        "APP_NAME": Config.APP_NAME,
        "COMPANY_NAME": Config.COMPANY_NAME,
    }


@app.route("/health")
def health():
    """Minimal health check (no DB). For Railway or load balancers."""
    return "ok", 200


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password(request.form.get("password", "")):
            session["authenticated"] = True
            return redirect(url_for("dashboard.index"))
        error = "Contraseña incorrecta."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500
