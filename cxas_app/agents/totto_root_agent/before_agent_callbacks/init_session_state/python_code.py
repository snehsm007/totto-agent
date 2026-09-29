from typing import Optional
import re


ORDER_ID_PATTERN = re.compile(
    r"(?:#((?:ORD-)?\d{4,8})\b|\b(?:order|commande|pedido|bestellung|bestellnummer)\b(?:\s+(?:number|num|no\.?|n[úu]mero|nr\.?|ist|is))?\s*:?\s*#?(\d{4,8}|ORD-\d{4,8})\b)",
    re.IGNORECASE,
)


def before_agent_callback(
    callback_context: CallbackContext,
) -> Optional[Content]:
    """Initializes default session state variables and extracts any order ID generically."""
    state = callback_context.state
    if "is_mock_mode" not in state:
        state["is_mock_mode"] = True
    if "user_timezone" not in state:
        state["user_timezone"] = ""
    if "user_location" not in state:
        state["user_location"] = ""
    if "order_id" not in state:
        state["order_id"] = ""

    for part in callback_context.get_last_user_input():
        text = part.text_or_transcript() or ""
        match = ORDER_ID_PATTERN.search(text)
        if match:
            raw_id = (match.group(1) or match.group(2) or "").strip()
            digits_match = re.search(r"(\d{4,8})", raw_id)
            state["order_id"] = digits_match.group(1) if digits_match else raw_id
    return None
