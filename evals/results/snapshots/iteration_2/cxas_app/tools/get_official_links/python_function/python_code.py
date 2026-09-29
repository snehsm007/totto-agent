"""Official Formula 1 ticketing and Mercedes-AMG PETRONAS F1 link directory tool."""

from typing import Any


CATEGORY_ALIASES: dict[str, str] = {
    "ticketing": "ticketing",
    "tickets": "ticketing",
    "ticket": "ticketing",
    "merch": "merch",
    "merchandise": "merch",
    "store": "merch",
    "shop": "merch",
    "team": "team",
    "social": "team",
    "fan": "team",
    "all": "all",
}


def get_official_links(category: str = "all") -> dict[str, Any]:
    """Retrieves verified official links for Formula 1 ticketing, Mercedes F1 store, and team channels.

    Before calling this tool, speak a brief conversational pacing phrase:
    Let me grab the official link for you.

    Args:
        category: Link category ('ticketing', 'merch', 'team', or 'all').

    Returns:
        Dictionary containing verified official URLs and non-transactional guidance.
    """
    raw_cat = str(category or "all").strip().lower()
    clean_cat = CATEGORY_ALIASES.get(raw_cat, "")

    links: dict[str, dict[str, str]] = {
        "ticketing": {
            "title": "Official Formula 1 Tickets",
            "url": "https://tickets.formula1.com",
            "guidance": (
                "Visit the official Formula 1 ticketing portal for live seat availability, "
                "grandstand pricing, general admission, and hospitality packages. "
                "Totto cannot check live seat inventory, quote prices, or book tickets directly."
            ),
        },
        "merch": {
            "title": "Official Mercedes-AMG Petronas F1 Team Store",
            "url": "https://shop.mercedesamgf1.com",
            "guidance": (
                "Explore official Silver Arrows teamwear, George Russell #63 and Kimi Antonelli #12 "
                "driver caps, hoodies, and collectibles on the official store."
            ),
        },
        "team": {
            "title": "Mercedes-AMG Petronas F1 Official Hub",
            "url": "https://www.mercedesamgf1.com",
            "guidance": (
                "Follow official Mercedes-AMG PETRONAS F1 news, race debriefs, and fan club updates."
            ),
        },
    }

    if not clean_cat:
        return {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_CATEGORY",
            "error_message": (
                f"Unknown link category '{category}'. "
                "Valid categories are: ticketing, merch, team, all."
            ),
        }

    disclaimer = (
        "Totto provides official referral links only and does not sell, reserve, price, "
        "or process payments for tickets or merchandise."
    )

    if clean_cat == "all":
        return {
            "status": "success",
            "category": "all",
            "links": links,
            "result": links["ticketing"],
            "non_transactional_disclaimer": disclaimer,
            "agent_action": "PROVIDE_OFFICIAL_LINKS",
        }

    return {
        "status": "success",
        "category": clean_cat,
        "result": links[clean_cat],
        "links": {clean_cat: links[clean_cat]},
        "non_transactional_disclaimer": disclaimer,
        "agent_action": "PROVIDE_OFFICIAL_LINKS",
    }
