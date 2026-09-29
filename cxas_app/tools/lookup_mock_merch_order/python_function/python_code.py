"""Mocked merchandise order lookup tool for Totto, Mercedes F1 Fan Agent."""

import re
from typing import Any


MOCK_DISCLAIMER = (
    "Note: This order data is mocked and simulated for demonstration purposes only. "
    "No real orders, payments, or personal data are processed."
)

MOCK_ORDERS: dict[str, dict[str, Any]] = {
    "1001": {
        "order_id": "1001",
        "status": "Delivered",
        "item": "Mercedes-AMG Petronas F1 2026 George Russell #63 Team Cap (Silver/Black)",
        "quantity": 1,
        "delivery_date": "Yesterday, 2:15 PM",
        "carrier": "DHL Express",
        "tracking_number": "DHL-MB-984210",
        "return_eligible": True,
        "return_window": "30 days from delivery (free prepaid return label available)",
        "exchange_policy": "Free size or colorway exchange within 30 days; Silver and Black caps are in stock.",
        "damaged_item_policy": (
            "Eligible for immediate no-cost replacement on damaged items using only your order number #1001."
        ),
        "product_availability": "In Stock (One Size Adjustable, Silver/Black & Team Teal)",
    },
    "1002": {
        "order_id": "1002",
        "status": "In Transit",
        "item": "Mercedes F1 W17 Kimi Antonelli #12 Graphic T-Shirt (Size L)",
        "quantity": 2,
        "estimated_delivery": "Within 2 business days",
        "carrier": "FedEx Ground",
        "tracking_number": "FX-MB-771923",
        "return_eligible": True,
        "return_window": "30 days after delivery",
        "exchange_policy": "Size exchanges (S, M, L, XL, XXL) can be initiated as soon as the parcel arrives.",
        "damaged_item_policy": (
            "If the item arrives damaged, report order #1002 for an instant mocked replacement dispatch."
        ),
        "product_availability": "In Stock across sizes S, M, L, XL, XXL",
    },
    "1003": {
        "order_id": "1003",
        "status": "Return In Progress",
        "item": "Mercedes-AMG Petronas Team Softshell Jacket (Size M)",
        "quantity": 1,
        "return_status": "Prepaid return label generated, awaiting carrier drop-off",
        "carrier": "DHL Express",
        "tracking_number": "DHL-RET-331099",
        "return_eligible": True,
        "return_window": "Active return (#DHL-RET-331099)",
        "exchange_policy": "Exchange for Size L reserved in mock warehouse pending carrier scan.",
        "damaged_item_policy": "Damaged zipper claim noted in mock system; replacement jacket ready to ship.",
        "product_availability": "Size S, M, L, XL in stock; XXL limited availability",
    },
}


def lookup_mock_merch_order(order_id: str = "") -> dict[str, Any]:
    """Looks up a mocked Mercedes F1 merchandise order by order number.

    Args:
        order_id: 4-digit mock order number (e.g. '1001', '1002', '1003', or '9999').

    Returns:
        Dictionary with mocked order status, return/exchange/damaged-item policies, and mock disclosure.
    """
    cleaned = str(order_id or "").strip()
    cleaned = re.sub(r"^(?:order|ord)[\s\-:#]*", "", cleaned, flags=re.IGNORECASE)
    clean_id = cleaned.lstrip("#").strip()

    if not clean_id:
        return {
            "status": "error",
            "found": False,
            "order_id": "",
            "agent_action": "PROMPT_FOR_ORDER_ID",
            "error_message": (
                "Please provide your 4-digit mock order number (e.g. #1001, #1002, or #1003). "
                "Only an order number is needed for this mocked demo."
            ),
            "sample_order_ids": ["1001", "1002", "1003"],
            "is_mock_data": True,
            "is_mock": True,
            "disclaimer": MOCK_DISCLAIMER,
        }

    if clean_id in MOCK_ORDERS:
        order_info = dict(MOCK_ORDERS[clean_id])
        order_info["is_mock_data"] = True
        order_info["is_mock"] = True
        order_info["disclaimer"] = MOCK_DISCLAIMER
        return {
            "status": "success",
            "found": True,
            "order_id": clean_id,
            "order": order_info,
            "is_mock_data": True,
            "is_mock": True,
            "disclaimer": MOCK_DISCLAIMER,
            "agent_action": "SHARE_MOCK_ORDER_DETAILS",
        }

    return {
        "status": "error",
        "agent_action": "OFFER_SAMPLE_ORDER_IDS",
        "found": False,
        "order_id": clean_id,
        "error_message": (
            f"Order #{clean_id} was not found in the demo system. "
            "Try sample orders #1001 (Delivered), #1002 (In Transit), or #1003 (Return In Progress)."
        ),
        "sample_order_ids": ["1001", "1002", "1003"],
        "is_mock_data": True,
        "is_mock": True,
        "disclaimer": MOCK_DISCLAIMER,
    }
