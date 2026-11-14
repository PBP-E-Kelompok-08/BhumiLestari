import requests
from django.conf import settings


REQUEST_TIMEOUT = 15


def _api_url(path):
    base_url = settings.MOCK_API_BASE_URL.rstrip("/")
    return f"{base_url}/api/v1/{path.lstrip('/')}"


def _write_headers():
    return {"X-Mock-Api-Key": settings.MOCK_API_WRITE_TOKEN}


def _product_payload(product):
    return {
        "name": product.name,
        "seller_id": product.seller.external_id,
        "seller_name": product.seller.store_name,
        "materials": [
            material.strip().lower()
            for material in product.materials.split(",")
            if material.strip()
        ],
        "origin": product.origin,
        "eco_features": list(
            product.eco_features.order_by("name").values_list("name", flat=True)
        ),
    }


def sync_product_to_mock_api(product):
    """Create/update a remote product and upload its private document."""
    try:
        payload = _product_payload(product)
        headers = _write_headers()

        if product.external_product_id:
            response = requests.patch(
                _api_url(f"products/{product.external_product_id}/"),
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                return False
        else:
            response = requests.post(
                _api_url("products/"),
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 201:
                return False
            product.external_product_id = response.json()["data"]["product_id"]
            product.save(update_fields=["external_product_id"])

        with product.verification_document.open("rb") as document:
            document_response = requests.post(
                _api_url(
                    f"products/{product.external_product_id}/document/"
                ),
                files={"verification_document": document},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        return document_response.status_code == 201
    except (requests.RequestException, KeyError, TypeError, ValueError, OSError):
        return False


def refresh_product_status_from_mock_api(product):
    if not product.external_product_id:
        return sync_product_to_mock_api(product)

    try:
        response = requests.get(
            _api_url(f"products/{product.external_product_id}/"),
            timeout=5,
        )
        if response.status_code != 200:
            return False

        verification = response.json()["data"].get("verification")
        if verification is None:
            return False

        product.status = verification["status"]
        product.verification_summary = verification.get("summary") or ""
        product.save(update_fields=["status", "verification_summary"])
        return True
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return False


def sync_verification_decision_to_mock_api(product):
    if not product.external_product_id:
        return False

    try:
        detail_response = requests.get(
            _api_url(f"products/{product.external_product_id}/"),
            timeout=5,
        )
        if detail_response.status_code != 200:
            return False
        verification = detail_response.json()["data"].get("verification")
        if not verification or not verification.get("verification_id"):
            return False

        response = requests.patch(
            _api_url(
                f"verifications/{verification['verification_id']}/"
            ),
            json={
                "status": product.status,
                "summary": product.verification_summary,
            },
            headers=_write_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        return response.status_code == 200
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return False


def delete_product_from_mock_api(product):
    if not product.external_product_id:
        return True

    try:
        response = requests.delete(
            _api_url(f"products/{product.external_product_id}/"),
            headers=_write_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        return response.status_code in {200, 204, 404}
    except requests.RequestException:
        return False
