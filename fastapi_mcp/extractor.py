from typing import Any, Dict, Iterable


def extract_structured_content(
    data: Dict[str, Any],
    keys: Iterable[str],
) -> Dict[str, Any]:
    """
    Extracts selected fields from a JSON dict.
    Supports dot-notation for nested fields.

    Example key: "inner_result.some_inner_variable"
    """
    result: Dict[str, Any] = {}

    for key in keys:
        current = data
        parts = key.split(".")

        try:
            for part in parts:
                current = current[part]
            result[parts[-1]] = current
        except (KeyError, TypeError):
            # Field not found → skip silently
            continue

    return result
