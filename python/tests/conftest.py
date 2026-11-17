import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def make_ez():
    """Create EasyAPI instances and always uninstall the tracer afterwards."""
    from easyapi import EasyAPI

    created = []

    def _make(app, **kw):
        kw.setdefault("store", "memory")
        kw.setdefault("roots", [ROOT])
        ez = EasyAPI(app, **kw)
        created.append(ez)
        return ez

    yield _make
    for ez in created:
        ez.close()


@pytest.fixture
def loja(make_ez):
    from fastapi.testclient import TestClient

    from examples.loja.main import create_app

    app = create_app()
    ez = make_ez(app)
    client = TestClient(app, raise_server_exceptions=False)
    return app, ez, client


def get_execution(client, response):
    ex_id = response.headers["x-easyapi-execution"]
    r = client.get(f"/_easyapi/api/executions/{ex_id}")
    assert r.status_code == 200, r.text
    return r.json()


def frame_by_fn(ex, suffix):
    matches = [f for f in ex["frames"] if f["fn"].endswith(suffix)]
    assert matches, f"no frame {suffix}: {[f['fn'] for f in ex['frames']]}"
    return matches[0]


def overlay_of(ex, frame):
    return next(o for o in ex["overlay"]["frames"] if o["id"] == frame["id"])
