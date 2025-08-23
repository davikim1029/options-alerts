# modeltest.py

import importlib
import requests
import os
from pydantic import ValidationError, parse_obj_as

def validate_api_model(url: str, model_name: str):
    auth = os.getenv("MODELTEST_BEARER")
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}

    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"[ERROR] API returned status {r.status_code}")
        return

    data = r.json()
    try:
        mod = importlib.import_module("models.generated." + model_name)
        model_class = getattr(mod, model_name)
        parsed = parse_obj_as(model_class, data)
        print(f"[SUCCESS] Data matched {model_name} model")
    except ValidationError as ve:
        print(f"[FAILURE] Validation error in {model_name}:")
        print(ve)
    except Exception as e:
        print(f"[ERROR] Failed to load model: {e}")
