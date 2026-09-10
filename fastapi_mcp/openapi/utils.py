import copy
from typing import Any, Dict, FrozenSet, Optional


def _variant_tag_value(variant: Dict[str, Any], tag_name: Optional[str]) -> Optional[str]:
    """The discriminator tag value a union variant fixes, if it can be determined."""
    if not tag_name:
        return None
    tag_schema = variant.get("properties", {}).get(tag_name, {})
    if "const" in tag_schema:
        return tag_schema["const"]
    enum_values = tag_schema.get("enum", [])
    if len(enum_values) == 1:
        return enum_values[0]
    return None


def build_union_body_input_schema(schema: Dict[str, Any], operation_id: str) -> Dict[str, Any]:
    """
    Build a flat tool input schema for a top-level union request body (oneOf/anyOf).

    FastAPI emits a discriminated Union body (e.g. `body: Annotated[Union[A, B],
    Field(discriminator='scope')]`) as a schema with oneOf/anyOf branches and no
    top-level "properties". Flattening only "properties" would advertise the tool
    as taking no arguments, so schema-abiding clients call it with `{}` and the
    endpoint rejects the call with a validation error.

    The union is deliberately NOT reproduced at the top level of the tool schema:
    composition keywords there are rejected or mishandled by several MCP hosts
    (Anthropic's direct tools API rejects top-level oneOf/anyOf/allOf outright;
    Microsoft Copilot Studio's connector layer surfaces such a tool with no
    parameters at all, so its model calls it with `{}`). Instead the branches'
    properties are merged into one flat object: keys required by *every* branch
    are marked required, the discriminator property is widened to an enum of all
    its tag values, and the schema description summarizes which fields each
    variant requires. Exact per-variant validation stays where it always was —
    the endpoint's own model (e.g. Pydantic's discriminated union).
    """
    variant_key = "oneOf" if "oneOf" in schema else "anyOf"
    variants = [v for v in schema.get(variant_key, []) if isinstance(v, dict)]

    merged_properties: Dict[str, Any] = {}
    merged_required: Optional[FrozenSet[str]] = None
    for variant in variants:
        variant_properties = variant.get("properties", {})
        for prop_name, prop_schema in variant_properties.items():
            if prop_name not in merged_properties:
                merged_properties[prop_name] = copy.deepcopy(prop_schema)
            elif merged_properties[prop_name] != prop_schema:
                # Branches disagree on this property's shape. Keep the key visible
                # as a hint, but leave validation to the endpoint so a value that
                # is valid for one branch is never rejected by the merged hint.
                merged_properties[prop_name] = {"title": prop_name}
        variant_required = frozenset(variant.get("required", variant_properties.keys()))
        merged_required = variant_required if merged_required is None else merged_required & variant_required

    discriminator = schema.get("discriminator")
    tag_name = discriminator.get("propertyName") if discriminator else None
    if discriminator and tag_name:
        tag_values = list(discriminator.get("mapping", {}).keys())
        if not tag_values:
            for variant in variants:
                tag_value = _variant_tag_value(variant, tag_name)
                if tag_value is not None:
                    tag_values.append(tag_value)
        if tag_values:
            merged_properties[tag_name] = {
                "type": "string",
                "enum": tag_values,
                "title": tag_name,
                "description": "Selects which argument variant applies (see the schema description).",
            }

    # Summarize per-variant requirements, since flattening loses branch-specific
    # `required` lists. Clients and models read this instead of a oneOf.
    summary_lines = []
    for variant in variants:
        variant_properties = variant.get("properties", {})
        required_fields = [r for r in variant.get("required", list(variant_properties.keys())) if r != tag_name]
        tag_value = _variant_tag_value(variant, tag_name)
        if tag_value is not None:
            label = f"{tag_name}={tag_value!r}"
        else:
            label = variant.get("title") or "variant"
        requires = ", ".join(required_fields) if required_fields else "no other fields"
        summary_lines.append(f"- {label}: requires {requires}")

    input_schema: Dict[str, Any] = {
        "type": "object",
        "properties": merged_properties,
        "title": f"{operation_id}Arguments",
    }
    if summary_lines:
        input_schema["description"] = "Exactly one variant of arguments applies:\n" + "\n".join(summary_lines)
    if merged_required:
        input_schema["required"] = sorted(merged_required)
    return input_schema


def unwrap_optional_body_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unwrap a top-level ``oneOf``/``anyOf`` of exactly [object schema, {"type": "null"}] to the
    object schema itself.

    FastAPI represents an *optional* request body (``body: Model | None = None``) as
    ``{"anyOf": [<Model schema>, {"type": "null"}], ...}`` with no top-level "properties" key --
    the same shape a genuine discriminated union body has. Left unrecognized, this schema is
    routed into `build_union_body_input_schema`, which fabricates a fictitious
    "Exactly one variant of arguments applies" description and leaks the model's internal name
    (e.g. "- ModelName: requires no other fields") for a body that is not a union at all; it is a
    single optional model. Callers must apply this before classifying a body schema as a union so
    an optional-body operation's tool input schema (properties, required, description) comes out
    identical to the same body declared required. A schema that does not match this exact
    two-variant [object, null] shape (a real union, or an optional body of a non-object type) is
    returned unchanged.
    """
    variant_key = "oneOf" if "oneOf" in schema else "anyOf" if "anyOf" in schema else None
    if variant_key is None:
        return schema
    variants = [v for v in schema.get(variant_key, []) if isinstance(v, dict)]
    if len(variants) != 2:
        return schema
    null_variants = [v for v in variants if v.get("type") == "null"]
    object_variants = [v for v in variants if v.get("type") != "null" and "properties" in v]
    if len(null_variants) != 1 or len(object_variants) != 1:
        return schema
    return object_variants[0]


def is_union_schema(param_schema: Dict[str, Any]) -> bool:
    """
    Whether the schema is a union (anyOf/oneOf/allOf) that must be preserved as-is.

    A union like `str | None` (anyOf[string, null]) already validates correctly on
    its own, including its null branch. Callers must not add a flattened top-level
    "type" next to it: JSON Schema enforces sibling keywords conjunctively, so
    `{"anyOf": [...], "type": "string"}` rejects an explicit null even though the
    anyOf allows it.
    """
    return any(key in param_schema for key in ("anyOf", "oneOf", "allOf"))


def get_single_param_type_from_schema(param_schema: Dict[str, Any]) -> str:
    """
    Get the type of a parameter from the schema.
    If the schema is a union type, return the first type.
    """
    if "anyOf" in param_schema:
        types = {schema.get("type") for schema in param_schema["anyOf"] if schema.get("type")}
        if "null" in types:
            types.remove("null")
        if types:
            return next(iter(types))
        return "string"
    return param_schema.get("type", "string")


def resolve_schema_references(
    schema_part: Dict[str, Any],
    reference_schema: Dict[str, Any],
    _seen_refs: Optional[FrozenSet[str]] = None,
) -> Dict[str, Any]:
    """
    Resolve schema references in OpenAPI schemas.

    Args:
        schema_part: The part of the schema being processed that may contain references
        reference_schema: The complete schema used to resolve references from
        _seen_refs: Internal use only. $ref paths already inlined along the current
            recursion branch. Self- or mutually-referential models (e.g. a tree-shaped
            schema whose "children" field references its own type) would otherwise
            inline the same $ref forever and blow the stack; once a $ref reappears on
            its own branch it is left as a $ref instead of being inlined again.

    Returns:
        The schema with references resolved
    """
    seen_refs = _seen_refs or frozenset()

    # Make a copy to avoid modifying the input schema
    schema_part = schema_part.copy()

    # Handle $ref directly in the schema
    if "$ref" in schema_part:
        ref_path = schema_part["$ref"]
        # Standard OpenAPI references are in the format "#/components/schemas/ModelName"
        if ref_path.startswith("#/components/schemas/") and ref_path not in seen_refs:
            model_name = ref_path.split("/")[-1]
            if "components" in reference_schema and "schemas" in reference_schema["components"]:
                if model_name in reference_schema["components"]["schemas"]:
                    # Replace with the resolved schema
                    ref_schema = reference_schema["components"]["schemas"][model_name].copy()
                    # Remove the $ref key and merge with the original schema
                    schema_part.pop("$ref")
                    schema_part.update(ref_schema)
                    seen_refs = seen_refs | {ref_path}

    # Recursively resolve references in all dictionary values
    for key, value in schema_part.items():
        if isinstance(value, dict):
            schema_part[key] = resolve_schema_references(value, reference_schema, seen_refs)
        elif isinstance(value, list):
            # Only process list items that are dictionaries since only they can contain refs
            schema_part[key] = [
                resolve_schema_references(item, reference_schema, seen_refs) if isinstance(item, dict) else item
                for item in value
            ]

    return schema_part


def clean_schema_for_display(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean up a schema for display by removing internal fields.

    Args:
        schema: The schema to clean

    Returns:
        The cleaned schema
    """
    # Make a copy to avoid modifying the input schema
    schema = schema.copy()

    # Remove common internal fields that are not helpful for LLMs
    fields_to_remove = [
        "allOf",
        "anyOf",
        "oneOf",
        "nullable",
        "discriminator",
        "readOnly",
        "writeOnly",
        "xml",
        "externalDocs",
    ]
    for field in fields_to_remove:
        if field in schema:
            schema.pop(field)

    # Process nested properties
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            if isinstance(prop_schema, dict):
                schema["properties"][prop_name] = clean_schema_for_display(prop_schema)

    # Process array items
    if "type" in schema and schema["type"] == "array" and "items" in schema:
        if isinstance(schema["items"], dict):
            schema["items"] = clean_schema_for_display(schema["items"])

    return schema


def generate_example_from_schema(schema: Dict[str, Any]) -> Any:
    """
    Generate a simple example response from a JSON schema.

    Args:
        schema: The JSON schema to generate an example from

    Returns:
        An example object based on the schema
    """
    if not schema or not isinstance(schema, dict):
        return None

    # Handle different types
    schema_type = schema.get("type")

    if schema_type == "object":
        result = {}
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                # Generate an example for each property
                prop_example = generate_example_from_schema(prop_schema)
                if prop_example is not None:
                    result[prop_name] = prop_example
        return result

    elif schema_type == "array":
        if "items" in schema:
            # Generate a single example item
            item_example = generate_example_from_schema(schema["items"])
            if item_example is not None:
                return [item_example]
        return []

    elif schema_type == "string":
        # Check if there's a format
        format_type = schema.get("format")
        if format_type == "date-time":
            return "2023-01-01T00:00:00Z"
        elif format_type == "date":
            return "2023-01-01"
        elif format_type == "email":
            return "user@example.com"
        elif format_type == "uri":
            return "https://example.com"
        # Use title or property name if available
        return schema.get("title", "string")

    elif schema_type == "integer":
        return 1

    elif schema_type == "number":
        return 1.0

    elif schema_type == "boolean":
        return True

    elif schema_type == "null":
        return None

    # Default case
    return None
