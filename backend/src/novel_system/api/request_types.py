from __future__ import annotations

from typing import Annotated, Any

from pydantic import WithJsonSchema


# Runtime shape validation deliberately remains in the writer-review domain
# normalizers so malformed briefs keep the stable WRITER_BRIEF_INVALID / 400
# contract.  The explicit schema prevents that implementation detail from
# advertising arbitrary JSON to OpenAPI clients.
WriterBriefJsonInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "object", "additionalProperties": True},
                {"type": "null"},
            ]
        }
    ),
]
