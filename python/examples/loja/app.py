"""ASGI entry point with Glowtrace enabled: uvicorn examples.loja.app:app"""
from glowtrace import Glowtrace

from .main import create_app

app = create_app()
Glowtrace(app)
