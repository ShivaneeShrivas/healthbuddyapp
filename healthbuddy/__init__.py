"""HealthBuddy application factory."""
from flask import Flask, render_template

from .config import Config
from .db import close_db, init_db


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    init_db(app)
    app.teardown_appcontext(close_db)

    # CORS for the native phone app: its screens are bundled on-device and
    # call this API from a different origin. Tokens travel in the
    # Authorization header (no cookies), so a permissive policy is safe here.
    @app.after_request
    def add_cors_headers(resp):
        from flask import request
        if request.path.startswith("/api"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        return resp

    @app.before_request
    def handle_preflight():
        from flask import request
        if request.method == "OPTIONS" and request.path.startswith("/api"):
            return "", 204

    from .routes.api import api
    app.register_blueprint(api)

    from .routes.features import bp as features_bp
    app.register_blueprint(features_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
