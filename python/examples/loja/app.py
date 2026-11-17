"""ASGI entry point with EasyAPI enabled: uvicorn examples.loja.app:app"""
from easyapi import EasyAPI

from .main import create_app

app = create_app()
EasyAPI(app)
