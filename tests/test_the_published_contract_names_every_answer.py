import httpx
import pytest_asyncio

from exchange_router.service import app


TITLES = ["Invalid Request", "Unknown Symbol", "Not Found", "Not Implemented", "Bad Upstream Response", "Upstream Unavailable", "Internal Server Error"]


@pytest_asyncio.fixture
async def published():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router.test") as http:
        yield (await http.get("/openapi.json")).json()


def target(schema):
    return schema.get("$ref") or (schema.get("items") or {}).get("$ref") or schema.get("type")


async def test_every_route_publishes_its_answer_and_the_six_error_answers(published):
    for path, operations in published["paths"].items():
        responses = operations["get"]["responses"]

        assert set(responses) == {"200", "400", "404", "500", "501", "502", "503"}, path
        assert target(responses["200"]["content"]["application/json"]["schema"]), path
        for status in ("400", "404", "500", "501", "502", "503"):
            assert responses[status]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorBody"}, path


async def test_the_validation_answer_fastapi_adds_is_gone(published):
    schemas = published["components"]["schemas"]

    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert all("422" not in operations["get"]["responses"] for operations in published["paths"].values())


async def test_every_field_of_every_model_is_required_the_nullable_ones_too(published):
    for name, schema in published["components"]["schemas"].items():
        if "properties" in schema:
            assert sorted(schema.get("required", [])) == sorted(schema["properties"]), name

    mark = published["components"]["schemas"]["MarkPrice"]
    assert {"index_price", "funding"} <= set(mark["required"])


async def test_the_error_body_is_one_of_seven_titles_and_a_sentence(published):
    body = published["components"]["schemas"]["ErrorBody"]

    assert body["properties"]["error"]["enum"] == TITLES
    assert body["required"] == ["error", "detail"]


async def test_a_kind_is_an_open_string_and_only_fixed_sets_are_enums(published):
    schemas = published["components"]["schemas"]
    closed  = sorted((name, field) for name, schema in schemas.items() for field, spec in schema.get("properties", {}).items() if "enum" in spec or "const" in spec)

    assert closed == [("AggTrade", "side"), ("ErrorBody", "error"), ("Liquidation", "side"), ("PriceSignificantFigures", "kind"), ("PriceTick", "kind"), ("Trade", "side")]
    assert schemas["MarginTiers"]["properties"]["up_to_unit"]["type"] == "string"
    assert schemas["LongShortRatio"]["properties"]["account_scope"]["type"] == "string"


async def test_a_trades_qty_extends_the_one_base_the_book_carries_bare(published):
    schemas = published["components"]["schemas"]

    assert list(schemas["QtyUnit"]["properties"])  == ["unit", "contract_size"]
    assert list(schemas["QtyValue"]["properties"]) == ["unit", "contract_size", "native", "notional"]
    assert schemas["OrderBook"]["properties"]["qty"]["$ref"] == "#/components/schemas/QtyUnit"
