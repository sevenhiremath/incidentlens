import os

import requests
from dotenv import load_dotenv

load_dotenv()
BASE_URL = os.getenv("INCIDENTLENS_API_URL", "http://127.0.0.1:8000/api").rstrip("/")


class APIError(Exception):
    pass


def call(method, path, *, token=None, **kwargs):
    headers = {"Authorization": f"Token {token}"} if token else {}
    try:
        response = requests.request(
            method,
            f"{BASE_URL}/{path.lstrip('/')}",
            headers=headers,
            timeout=10,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise APIError("Cannot reach the API. Check that the backend is running.") from exc
    if response.status_code == 204:
        return None
    try:
        data = response.json()
    except ValueError as exc:
        raise APIError("The API returned an unexpected response.") from exc
    if not response.ok:
        if response.status_code == 401:
            raise APIError("Please log in again. Your session is missing or expired.")
        raise APIError(f"Request failed ({response.status_code}): {data}")
    return data


def page(path, token, *, params=None):
    return call("GET", path, token=token, params=params)
