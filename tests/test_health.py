import importlib
import types

def _get_app():
    # si ton app Flask est dans app.py et expose "app" ou "create_app"
    mod = importlib.import_module("app")
    if getattr(mod, "app", None) is not None:
        return mod.app
    if hasattr(mod, "create_app"):
        return mod.create_app()
    raise RuntimeError("Expose 'app' or 'create_app' in app.py")

def test_root_or_health():
    app = _get_app()
    client = app.test_client()
    for path in ("/health", "/"):
        resp = client.get(path)
        if resp.status_code < 400:
            assert resp.status_code == 200
            return
    raise AssertionError("Ni /health ni / ne répond 2xx")
