# http/health.py
from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)

@bp.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})
