"""Shared narrative fact taxonomy without service-to-service dependencies."""

INFORMATION_ASYMMETRY_FACT_KEYS = frozenset(
    {
        "secret_held_by",
        "believes_false",
        "revealed_to",
        "scene_revelation",
    }
)
