"""Mocked merch lookup (PRD AC5, L35, L137-138, L162) and official links (PRD AC4, L130-132, RC-01)."""

import pytest

MERCH_URL = "https://shop.mercedesamgf1.com"
TICKETS_URL = "https://tickets.formula1.com"
TEAM_URL = "https://www.mercedesamgf1.com"


@pytest.mark.finding("PRD-AC5", "PRD-L137")
@pytest.mark.parametrize(
    "order_input,expected_found,expected_status",
    [
        ("Order #1001", True, "Delivered"),
        ("order 1003", True, "Return In Progress"),
        ("  1002  ", True, "In Transit"),
        (1002, True, "In Transit"),
        ("123456", False, None),
        ("ABCD", False, None),
        ("1001; DROP TABLE orders", False, None),
        ("#", False, None),
    ],
)
def test_lookup_mock_merch_order_arbitrary_inputs(load_tool, order_input, expected_found, expected_status) -> None:
    res = load_tool("lookup_mock_merch_order")(order_id=order_input)
    assert res["found"] is expected_found, res
    if expected_found:
        assert res["status"] == "success" and res["order"]["status"] == expected_status
    else:
        assert res["status"] == "error"
        assert res["agent_action"] in ("OFFER_SAMPLE_ORDER_IDS", "PROMPT_FOR_ORDER_ID")
        assert "order" not in res, "an unknown order must not come back with order details"


@pytest.mark.finding("PRD-AC5", "PRD-L35", "PRD-L162")
@pytest.mark.parametrize("order_input", ["1001", "1002", "1003", "9999", "", "123456", None])
def test_every_merch_response_discloses_mock_data(load_tool, order_input) -> None:
    res = load_tool("lookup_mock_merch_order")(order_id=order_input)
    assert res["is_mock_data"] is True
    disclaimer = str(res.get("disclaimer", "")).lower()
    assert "mock" in disclaimer or "demo" in disclaimer, res.get("disclaimer")
    if res["status"] == "success":
        assert res["order"]["is_mock_data"] is True


@pytest.mark.finding("RC-01", "PRD-L132")
@pytest.mark.parametrize("category", ["merch", "merchandise", "store", "shop", "Store ", "SHOP"])
def test_merch_store_aliases_return_official_store(load_tool, category: str) -> None:
    res = load_tool("get_official_links")(category=category)
    assert res["status"] == "success", res
    assert res["result"]["url"] == MERCH_URL


@pytest.mark.finding("RC-01", "PRD-AC4", "PRD-L31", "PRD-L158")
@pytest.mark.parametrize("category", ["all", "both", "", None])
def test_all_links_include_every_official_destination_and_non_transactional_notice(load_tool, category) -> None:
    res = load_tool("get_official_links")(category=category)
    assert res["status"] == "success"
    urls = {entry["url"] for entry in res["links"].values()}
    assert {MERCH_URL, TICKETS_URL, TEAM_URL} <= urls
    notice = res.get("non_transactional_disclaimer", "").lower()
    assert "does not sell" in notice or "cannot" in notice or "not sell" in notice, notice


@pytest.mark.finding("PRD-AC4", "PRD-L161")
def test_ticket_link_guidance_claims_no_availability_or_price(load_tool) -> None:
    res = load_tool("get_official_links")(category="tickets")
    guidance = res["result"]["guidance"].lower()
    assert res["result"]["url"] == TICKETS_URL
    assert "cannot" in guidance and ("price" in guidance or "inventory" in guidance)
