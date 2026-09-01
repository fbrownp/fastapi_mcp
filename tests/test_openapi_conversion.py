from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
import mcp.types as types

from fastapi_mcp.openapi.convert import convert_openapi_to_mcp_tools
from fastapi_mcp.openapi.utils import (
    clean_schema_for_display,
    generate_example_from_schema,
    get_single_param_type_from_schema,
    resolve_schema_references,
)


def test_simple_app_conversion(simple_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=simple_fastapi_app.title,
        version=simple_fastapi_app.version,
        openapi_version=simple_fastapi_app.openapi_version,
        description=simple_fastapi_app.description,
        routes=simple_fastapi_app.routes,
    )

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)

    assert len(tools) == 6
    assert len(operation_map) == 6

    expected_operations = ["list_items", "get_item", "create_item", "update_item", "delete_item", "raise_error"]
    for op in expected_operations:
        assert op in operation_map

    for tool in tools:
        assert isinstance(tool, types.Tool)
        assert tool.name in expected_operations
        assert tool.description is not None
        assert tool.inputSchema is not None


def test_complex_app_conversion(complex_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)

    expected_operations = ["list_products", "get_product", "create_order", "get_customer"]
    assert len(tools) == len(expected_operations)
    assert len(operation_map) == len(expected_operations)

    for op in expected_operations:
        assert op in operation_map

    for tool in tools:
        assert isinstance(tool, types.Tool)
        assert tool.name in expected_operations
        assert tool.description is not None
        assert tool.inputSchema is not None


def test_describe_full_response_schema(simple_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=simple_fastapi_app.title,
        version=simple_fastapi_app.version,
        openapi_version=simple_fastapi_app.openapi_version,
        description=simple_fastapi_app.description,
        routes=simple_fastapi_app.routes,
    )

    tools_full, _ = convert_openapi_to_mcp_tools(openapi_schema, describe_full_response_schema=True)

    tools_simple, _ = convert_openapi_to_mcp_tools(openapi_schema, describe_full_response_schema=False)

    for i, tool in enumerate(tools_full):
        assert tool.description is not None
        assert tools_simple[i].description is not None

        tool_desc = tool.description or ""
        simple_desc = tools_simple[i].description or ""

        assert len(tool_desc) >= len(simple_desc)

        if tool.name == "delete_item":
            continue

        assert "**Output Schema:**" in tool_desc

        if "**Output Schema:**" in simple_desc:
            assert len(tool_desc) > len(simple_desc)


def test_describe_all_responses(complex_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    tools_all, _ = convert_openapi_to_mcp_tools(openapi_schema, describe_all_responses=True)

    tools_success, _ = convert_openapi_to_mcp_tools(openapi_schema, describe_all_responses=False)

    create_order_all = next(t for t in tools_all if t.name == "create_order")
    create_order_success = next(t for t in tools_success if t.name == "create_order")

    assert create_order_all.description is not None
    assert create_order_success.description is not None

    all_desc = create_order_all.description or ""
    success_desc = create_order_success.description or ""

    assert "400" in all_desc
    assert "404" in all_desc
    assert "422" in all_desc

    assert all_desc.count("400") >= success_desc.count("400")


def test_schema_utils():
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id", "name"],
        "additionalProperties": False,
        "x-internal": "Some internal data",
    }

    cleaned = clean_schema_for_display(schema)

    assert "required" in cleaned
    assert "properties" in cleaned
    assert "type" in cleaned

    example = generate_example_from_schema(schema)
    assert "id" in example
    assert "name" in example
    assert "tags" in example
    assert isinstance(example["id"], int)
    assert isinstance(example["name"], str)
    assert isinstance(example["tags"], list)

    assert get_single_param_type_from_schema({"type": "string"}) == "string"
    assert get_single_param_type_from_schema({"type": "array", "items": {"type": "string"}}) == "array"

    array_schema = {"type": "array", "items": {"type": "string", "enum": ["red", "green", "blue"]}}
    array_example = generate_example_from_schema(array_schema)
    assert isinstance(array_example, list)
    assert len(array_example) > 0

    assert isinstance(array_example[0], str)


def test_parameter_handling(complex_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)

    list_products_tool = next(tool for tool in tools if tool.name == "list_products")

    properties = list_products_tool.inputSchema["properties"]

    assert "product_id" not in properties  # This is from get_product, not list_products

    assert "category" in properties
    # Nullable enum (`ProductCategory | None`): the anyOf union is preserved as-is
    # and no flattened sibling "type" is added — a top-level "type" next to the
    # anyOf would make an explicit null argument fail MCP input validation.
    assert "anyOf" in properties["category"]
    assert "type" not in properties["category"]
    assert "description" in properties["category"]
    assert "Filter by product category" in properties["category"]["description"]

    assert "min_price" in properties
    # `Optional[float]` query param: union preserved, no flattened sibling type.
    assert "anyOf" in properties["min_price"]
    assert "type" not in properties["min_price"]
    assert "description" in properties["min_price"]
    assert "Minimum price filter" in properties["min_price"]["description"]

    assert "in_stock_only" in properties
    assert properties["in_stock_only"].get("type") == "boolean"
    assert properties["in_stock_only"].get("default") is False  # Default value preserved

    assert "page" in properties
    assert properties["page"].get("type") == "integer"
    assert properties["page"].get("default") == 1  # Default value preserved
    if "minimum" in properties["page"]:
        assert properties["page"]["minimum"] >= 1  # ge=1 in Query param

    assert "size" in properties
    assert properties["size"].get("type") == "integer"
    if "minimum" in properties["size"] and "maximum" in properties["size"]:
        assert properties["size"]["minimum"] >= 1  # ge=1 in Query param
        assert properties["size"]["maximum"] <= 100  # le=100 in Query param

    assert "tag" in properties
    # `Optional[List[str]]` query param: union preserved, no flattened sibling type.
    assert "anyOf" in properties["tag"]
    assert "type" not in properties["tag"]

    required = list_products_tool.inputSchema.get("required", [])
    assert "page" not in required  # Has default value
    assert "category" not in required  # Optional parameter

    assert "list_products" in operation_map
    assert operation_map["list_products"]["path"] == "/products"
    assert operation_map["list_products"]["method"] == "get"

    get_product_tool = next(tool for tool in tools if tool.name == "get_product")
    get_product_props = get_product_tool.inputSchema["properties"]

    assert "product_id" in get_product_props
    assert get_product_props["product_id"].get("type") == "string"  # UUID converted to string
    assert "description" in get_product_props["product_id"]

    get_customer_tool = next(tool for tool in tools if tool.name == "get_customer")
    get_customer_props = get_customer_tool.inputSchema["properties"]

    assert "fields" in get_customer_props
    assert get_customer_props["fields"].get("type") == "array"
    if "items" in get_customer_props["fields"]:
        assert get_customer_props["fields"]["items"].get("type") == "string"


def test_request_body_handling(complex_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    create_order_route = openapi_schema["paths"]["/orders"]["post"]
    original_request_body = create_order_route["requestBody"]["content"]["application/json"]["schema"]
    original_properties = original_request_body.get("properties", {})

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)

    create_order_tool = next(tool for tool in tools if tool.name == "create_order")

    properties = create_order_tool.inputSchema["properties"]

    assert "customer_id" in properties
    assert "items" in properties
    assert "shipping_address_id" in properties
    assert "payment_method" in properties
    assert "notes" in properties

    for param_name in ["customer_id", "items", "shipping_address_id", "payment_method", "notes"]:
        if "description" in original_properties.get(param_name, {}):
            assert "description" in properties[param_name]
            assert properties[param_name]["description"] == original_properties[param_name]["description"]

    for param_name in ["customer_id", "items", "shipping_address_id", "payment_method", "notes"]:
        assert properties[param_name]["title"] == param_name

    for param_name in ["customer_id", "items", "shipping_address_id", "payment_method", "notes"]:
        if "default" in original_properties.get(param_name, {}):
            assert "default" in properties[param_name]
            assert properties[param_name]["default"] == original_properties[param_name]["default"]

    required = create_order_tool.inputSchema.get("required", [])
    assert "customer_id" in required
    assert "items" in required
    assert "shipping_address_id" in required
    assert "payment_method" in required
    assert "notes" not in required  # Optional in OrderRequest

    assert properties["items"].get("type") == "array"
    if "items" in properties["items"]:
        item_props = properties["items"]["items"]
        assert item_props.get("type") == "object"
        if "properties" in item_props:
            assert "product_id" in item_props["properties"]
            assert "quantity" in item_props["properties"]
            assert "unit_price" in item_props["properties"]
            assert "total" in item_props["properties"]

            for nested_param in ["product_id", "quantity", "unit_price", "total"]:
                assert "title" in item_props["properties"][nested_param]

                # Check if the original nested schema had descriptions
                original_item_schema = original_properties.get("items", {}).get("items", {}).get("properties", {})
                if "description" in original_item_schema.get(nested_param, {}):
                    assert "description" in item_props["properties"][nested_param]
                    assert (
                        item_props["properties"][nested_param]["description"]
                        == original_item_schema[nested_param]["description"]
                    )

    assert "create_order" in operation_map
    assert operation_map["create_order"]["path"] == "/orders"
    assert operation_map["create_order"]["method"] == "post"


def test_missing_type_handling(complex_fastapi_app: FastAPI):
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    # Remove the type field from the product_id schema
    params = openapi_schema["paths"]["/products/{product_id}"]["get"]["parameters"]
    for param in params:
        if param.get("name") == "product_id" and "schema" in param:
            param["schema"].pop("type", None)
            break

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)

    get_product_tool = next(tool for tool in tools if tool.name == "get_product")
    get_product_props = get_product_tool.inputSchema["properties"]

    assert "product_id" in get_product_props
    assert get_product_props["product_id"].get("type") == "string"  # Default type applied


def test_body_params_descriptions_and_defaults(complex_fastapi_app: FastAPI):
    """
    Test that descriptions and defaults from request body parameters
    are properly transferred to the MCP tool schema properties.
    """
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    order_request_schema = openapi_schema["components"]["schemas"]["OrderRequest"]

    order_request_schema["properties"]["customer_id"]["description"] = "Test customer ID description"
    order_request_schema["properties"]["payment_method"]["description"] = "Test payment method description"
    order_request_schema["properties"]["notes"]["default"] = "Default order notes"

    item_schema = openapi_schema["components"]["schemas"]["OrderItem"]
    item_schema["properties"]["product_id"]["description"] = "Test product ID description"
    item_schema["properties"]["quantity"]["default"] = 1

    tools, _ = convert_openapi_to_mcp_tools(openapi_schema)

    create_order_tool = next(tool for tool in tools if tool.name == "create_order")
    properties = create_order_tool.inputSchema["properties"]

    assert "description" in properties["customer_id"]
    assert properties["customer_id"]["description"] == "Test customer ID description"

    assert "description" in properties["payment_method"]
    assert properties["payment_method"]["description"] == "Test payment method description"

    assert "default" in properties["notes"]
    assert properties["notes"]["default"] == "Default order notes"

    if "items" in properties:
        assert properties["items"]["type"] == "array"
        assert "items" in properties["items"]

        item_props = properties["items"]["items"]["properties"]

        assert "description" in item_props["product_id"]
        assert item_props["product_id"]["description"] == "Test product ID description"

        assert "default" in item_props["quantity"]
        assert item_props["quantity"]["default"] == 1


def test_body_params_edge_cases(complex_fastapi_app: FastAPI):
    """
    Test handling of edge cases for body parameters, such as:
    - Empty or missing descriptions
    - Missing type information
    - Empty properties object
    - Schema without properties
    """
    openapi_schema = get_openapi(
        title=complex_fastapi_app.title,
        version=complex_fastapi_app.version,
        openapi_version=complex_fastapi_app.openapi_version,
        description=complex_fastapi_app.description,
        routes=complex_fastapi_app.routes,
    )

    order_request_schema = openapi_schema["components"]["schemas"]["OrderRequest"]

    if "description" in order_request_schema["properties"]["customer_id"]:
        del order_request_schema["properties"]["customer_id"]["description"]

    if "type" in order_request_schema["properties"]["notes"]:
        del order_request_schema["properties"]["notes"]["type"]

    item_schema = openapi_schema["components"]["schemas"]["OrderItem"]

    if "properties" in item_schema["properties"]["total"]:
        del item_schema["properties"]["total"]["properties"]

    tools, _ = convert_openapi_to_mcp_tools(openapi_schema)

    create_order_tool = next(tool for tool in tools if tool.name == "create_order")
    properties = create_order_tool.inputSchema["properties"]

    assert "customer_id" in properties
    assert "title" in properties["customer_id"]
    assert properties["customer_id"]["title"] == "customer_id"

    assert "notes" in properties
    # `notes` is `str | None`: the anyOf union survives conversion untouched and no
    # flattened "type" is stacked on it, so an explicit null stays valid.
    assert "anyOf" in properties["notes"]
    assert "type" not in properties["notes"]

    if "items" in properties:
        item_props = properties["items"]["items"]["properties"]
        assert "total" in item_props


def test_resolve_schema_references_self_recursive_model():
    """A schema whose $ref points back to itself (e.g. a tree-shaped model with
    children of its own type) must terminate instead of inlining forever."""
    reference_schema = {
        "components": {
            "schemas": {
                "TreeNode": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/TreeNode"},
                        },
                    },
                }
            }
        }
    }
    schema_part = {"$ref": "#/components/schemas/TreeNode"}

    resolved = resolve_schema_references(schema_part, reference_schema)

    assert resolved["type"] == "object"
    assert resolved["properties"]["name"] == {"type": "string"}
    # One level is inlined; the self-reference is left as a $ref rather than
    # being inlined again, which is what breaks the infinite recursion.
    child_items = resolved["properties"]["children"]["items"]
    assert child_items == {"$ref": "#/components/schemas/TreeNode"}


def test_resolve_schema_references_mutually_recursive_models():
    """Two models that reference each other (A -> B -> A) must also terminate."""
    reference_schema = {
        "components": {
            "schemas": {
                "Author": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "books": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Book"},
                        },
                    },
                },
                "Book": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "author": {"$ref": "#/components/schemas/Author"},
                    },
                },
            }
        }
    }
    schema_part = {"$ref": "#/components/schemas/Author"}

    resolved = resolve_schema_references(schema_part, reference_schema)

    book_item = resolved["properties"]["books"]["items"]
    assert book_item["properties"]["title"] == {"type": "string"}
    # Book -> Author is where the cycle closes; it stays a $ref.
    assert book_item["properties"]["author"] == {"$ref": "#/components/schemas/Author"}


def test_convert_openapi_to_mcp_tools_with_self_recursive_model():
    """End-to-end regression test for a tree-shaped response model: this used to
    raise RecursionError inside convert_openapi_to_mcp_tools (via
    resolve_schema_references) because self-referential $refs were inlined with
    no cycle detection."""
    from typing import List

    from pydantic import BaseModel

    class CatalogSection(BaseModel):
        section_key: str
        children: List["CatalogSection"] = []

    CatalogSection.model_rebuild()

    class CatalogResponse(BaseModel):
        sections: List[CatalogSection] = []

    app = FastAPI()

    @app.get("/catalog", operation_id="get_catalog", response_model=CatalogResponse)
    def get_catalog() -> CatalogResponse:
        return CatalogResponse()

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema, describe_full_response_schema=True)

    assert "get_catalog" in operation_map
    assert len(tools) == 1


def test_nullable_body_field_accepts_explicit_null():
    """A `str | None` body field must accept an explicit null argument.

    The MCP SDK jsonschema-validates tool arguments against the generated
    inputSchema before the endpoint runs. Pydantic emits `str | None` as
    anyOf[string, null]; stacking a flattened top-level `"type": "string"`
    next to that anyOf makes the null branch unsatisfiable (JSON Schema
    enforces sibling keywords conjunctively), so a model sending
    `{"keyword": null}` fails with "None is not of type 'string'" — observed
    killing agent turns in production.
    """
    from typing import Optional

    import jsonschema
    from pydantic import BaseModel, Field

    class SearchRequest(BaseModel):
        keyword: Optional[str] = Field(default=None, max_length=500)

    app = FastAPI()

    @app.post("/search", operation_id="search")
    def search(body: SearchRequest) -> dict:
        return {}

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )

    tools, _ = convert_openapi_to_mcp_tools(openapi_schema)
    input_schema = next(tool for tool in tools if tool.name == "search").inputSchema
    keyword_schema = input_schema["properties"]["keyword"]

    # The union must be preserved without a conflicting flattened sibling type.
    assert "anyOf" in keyword_schema
    assert "type" not in keyword_schema

    # The production contract: what the MCP SDK actually does with arguments.
    jsonschema.validate(instance={"keyword": None}, schema=input_schema)
    jsonschema.validate(instance={"keyword": "agua"}, schema=input_schema)
    jsonschema.validate(instance={}, schema=input_schema)

    # The union's own constraints still apply.
    import pytest

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={"keyword": 123}, schema=input_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={"keyword": "x" * 501}, schema=input_schema)


def test_non_union_body_field_still_gets_flattened_type():
    """Plain fields keep the existing behavior: a top-level type is ensured."""
    from pydantic import BaseModel

    class PlainRequest(BaseModel):
        name: str

    app = FastAPI()

    @app.post("/plain", operation_id="plain")
    def plain(body: PlainRequest) -> dict:
        return {}

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )

    tools, _ = convert_openapi_to_mcp_tools(openapi_schema)
    input_schema = next(tool for tool in tools if tool.name == "plain").inputSchema
    assert input_schema["properties"]["name"]["type"] == "string"
    assert input_schema["required"] == ["name"]


def test_discriminated_union_body_conversion():
    """A top-level discriminated Union request body must not produce an empty input schema.

    Regression test: endpoints declared as `body: Annotated[Union[A, B], Field(discriminator=...)]`
    have a requestBody schema with oneOf branches and no top-level "properties". They used to
    convert to `{"type": "object", "properties": {}}`, so schema-abiding clients called the tool
    with `{}` and the endpoint rejected the call with a Pydantic validation error.
    """
    from enum import Enum
    from typing import Annotated, Literal, Union

    from pydantic import BaseModel, ConfigDict, Field

    class NameScope(str, Enum):
        seia = "nombre_proyecto"
        uf = "nombre_uf"

    class BaseQuery(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class SeiaNameSearchQuery(BaseQuery):
        scope: Literal[NameScope.seia]
        name: str = Field(min_length=1, max_length=500)

    class UfNameSearchQuery(BaseQuery):
        scope: Literal[NameScope.uf]
        name: str = Field(min_length=1, max_length=500)

    NameSearchQuery = Annotated[
        Union[SeiaNameSearchQuery, UfNameSearchQuery],
        Field(discriminator="scope"),
    ]

    app = FastAPI()

    @app.post("/search-by-name", operation_id="search-by-name")
    async def search_by_name(body: NameSearchQuery):  # type: ignore[valid-type]
        return {"documents": []}

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )

    tools, operation_map = convert_openapi_to_mcp_tools(openapi_schema)
    assert len(tools) == 1
    input_schema = tools[0].inputSchema

    # The union branches survive, with their discriminator, for exact validation
    assert "oneOf" in input_schema
    assert len(input_schema["oneOf"]) == 2
    assert input_schema["discriminator"]["propertyName"] == "scope"

    # Merged top-level property hints for clients that ignore oneOf
    assert set(input_schema["properties"].keys()) == {"scope", "name"}
    assert sorted(input_schema["properties"]["scope"]["enum"]) == ["nombre_proyecto", "nombre_uf"]
    assert input_schema["properties"]["name"]["type"] == "string"

    # Keys required by every branch are required at the top level
    assert sorted(input_schema["required"]) == ["name", "scope"]

    # The tool remains a plain-object schema at the top level
    assert input_schema["type"] == "object"


def test_union_body_conflicting_property_hint():
    """When union branches disagree on a property's shape, the merged hint must not over-constrain."""
    from typing import Annotated, Literal, Union

    from pydantic import BaseModel, Field

    class VariantA(BaseModel):
        kind: Literal["a"]
        value: str

    class VariantB(BaseModel):
        kind: Literal["b"]
        value: int

    Query = Annotated[Union[VariantA, VariantB], Field(discriminator="kind")]

    app = FastAPI()

    @app.post("/conflict", operation_id="conflict")
    async def conflict(body: Query):  # type: ignore[valid-type]
        return {}

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )

    tools, _ = convert_openapi_to_mcp_tools(openapi_schema)
    input_schema = tools[0].inputSchema

    # `value` differs between branches: the hint stays visible but unconstrained,
    # so a payload valid for either branch is never rejected by the merged hint.
    assert "type" not in input_schema["properties"]["value"]
    assert sorted(input_schema["properties"]["kind"]["enum"]) == ["a", "b"]
    assert input_schema["required"] == ["kind", "value"]
