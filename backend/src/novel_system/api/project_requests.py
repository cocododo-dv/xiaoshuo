from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from novel_system.api.request_types import StrictRequestModel


class _ProjectFieldsRequest(StrictRequestModel):
    title: str | None = Field(default=None, max_length=500)
    genre: str | None = Field(default=None, max_length=255)
    mark: str | None = Field(default=None, max_length=32)
    accent: str | None = Field(default=None, max_length=128)
    synopsis_line: str | None = Field(default=None, max_length=4000)
    # HTML numeric inputs arrive as strings in the current client.  Accept that
    # representation deliberately, but reject malformed, non-positive, or
    # unreasonably large values before they reach the lenient legacy parser.
    target_word_count: int | str | None = None
    target_chapter_count: int | str | None = None
    words_target_daily: int | str | None = None

    @field_validator(
        "target_word_count",
        "target_chapter_count",
        "words_target_daily",
    )
    @classmethod
    def validate_positive_integer_input(cls, value: Any) -> Any:
        if value is None or value == "":
            return value
        if isinstance(value, bool):
            raise ValueError("value must be a positive integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be a positive integer") from exc
        if str(value).strip() != str(number) or not 1 <= number <= 2_147_483_647:
            raise ValueError("value must be a positive integer")
        return value


class ProjectCreateRequest(_ProjectFieldsRequest):
    # Omission remains a domain error so PROJECT_OUTLINE_REQUIRED is stable.
    outline_text: str | None = Field(default=None, max_length=2_000_000)
    planning_mode: str | None = Field(default=None, max_length=64)
    snowflake_workflow_mode: str | None = Field(default=None, max_length=64)


class ProjectProfileUpdateRequest(_ProjectFieldsRequest):
    pass
