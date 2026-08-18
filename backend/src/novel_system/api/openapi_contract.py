from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


SUCCESS_SCHEMA_NAME = "ApiSuccessEnvelope"
ERROR_SCHEMA_NAME = "ApiErrorEnvelope"
_OPERATION_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _schema_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(description: str, schema_name: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _schema_ref(schema_name)}},
    }


def _envelope_schemas() -> dict[str, Any]:
    request_id = {"type": "string", "pattern": r"^req_[0-9a-f]{12}$"}
    return {
        SUCCESS_SCHEMA_NAME: {
            "type": "object",
            "additionalProperties": False,
            "required": ["ok", "data", "error", "request_id"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "data": {"type": "object", "additionalProperties": True},
                "error": {"type": "null"},
                "request_id": request_id,
            },
        },
        "ApiError": {
            "type": "object",
            "additionalProperties": False,
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string", "minLength": 1},
                "message": {"type": "string"},
                "details": {"type": "object", "additionalProperties": True},
            },
        },
        ERROR_SCHEMA_NAME: {
            "type": "object",
            "additionalProperties": False,
            "required": ["ok", "data", "error", "request_id"],
            "properties": {
                "ok": {"type": "boolean", "const": False},
                "data": {"type": "null"},
                "error": _schema_ref("ApiError"),
                "request_id": request_id,
            },
        },
    }


def install_api_openapi_contract(
    app: FastAPI,
    *,
    api_prefixes: tuple[str, ...] = ("/api/v1/", "/api/v2/"),
) -> None:
    """Document the envelope already enforced by the API response helpers.

    Route handlers intentionally return ``JSONResponse`` so domain errors and
    idempotency headers stay under explicit control. FastAPI cannot infer a
    useful schema from that response class, therefore it otherwise publishes an
    empty ``{}`` response for every endpoint. This post-processor adds the
    actual cross-module contract without changing runtime serialization.
    """

    def contract_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
            separate_input_output_schemas=app.separate_input_output_schemas,
        )
        components = schema.setdefault("components", {})
        component_schemas = components.setdefault("schemas", {})
        component_schemas.update(_envelope_schemas())

        for path, path_item in schema.get("paths", {}).items():
            if not any(path.startswith(prefix) for prefix in api_prefixes) or not isinstance(path_item, Mapping):
                continue
            for method, operation in path_item.items():
                if method not in _OPERATION_METHODS or not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                for status_code, response in responses.items():
                    if status_code == "default" or not isinstance(response, dict):
                        continue
                    schema_name = SUCCESS_SCHEMA_NAME if str(status_code).startswith("2") else ERROR_SCHEMA_NAME
                    response.setdefault("content", {}).setdefault("application/json", {})["schema"] = _schema_ref(
                        schema_name
                    )
                responses.setdefault(
                    "default",
                    _json_response("Standard API error envelope", ERROR_SCHEMA_NAME),
                )

        app.openapi_schema = schema
        return schema

    app.openapi = contract_openapi
