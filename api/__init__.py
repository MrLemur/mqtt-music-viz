"""API package for mqtt-music-viz."""

from flask import Blueprint

bp = Blueprint("api", __name__)

# Import routes to register them with the blueprint
from . import routes
