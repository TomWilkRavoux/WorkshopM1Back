import importlib
import importlib.util
import sys
from pathlib import Path

def _load_app_module():
    # essaie import standard
    try:
        return importlib.import_module("app")
    except ModuleNotFoundError:
        # fallback: charge app.py par chemin depuis la racine du repo
        root = Path(__file__).resolve().parents[1]
        app_path = root / "app.py"
        if not app_path.exists():
            raise
        spec = importlib.util.spec_from_file_location("app", app_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app"] = mod
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod

def _get_app():
    mod = _load_app_module()
    if getattr(mod, "app", None) is not None:
        return mod.app
    if hasattr(mod, "create_app"):
        return mod.create_app()
    raise RuntimeError("Expose 'app' ou 'create_app' dans app.py")

def test_root_or_health():
    app = _get_app()
    client = app.test_client()
    for path in ("/health", "/"):
        resp = client.get(path)
        if resp.status_code < 400:
            assert resp.status_code == 200
            return
    raise AssertionError("Ni /health ni / ne répond 2xx")
