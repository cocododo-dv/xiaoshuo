"""Drop the machine-written 30s LLM timeout ceiling from api config snapshots.

Revision ID: 20260722_0074
Revises: 20260716_0073
Create Date: 2026-07-22

``llm.timeout_seconds: 30.0`` was never an authoring decision — it was stamped
onto every api snapshot by ``system_config``'s ``setdefault`` whenever a
provider was added, made default, or deleted.  A long extraction/synthesis on a
slow model is normal work, not a fault, yet that stamp cut it off mid-generation
with ``LLM_REQUEST_TIMEOUT``.  The runtime default is now ``0`` (no response
ceiling; connection setup keeps its own finite timeout), but a stored ``30.0``
would keep overriding it, so the stale stamp is removed here.

Only the exact legacy default is touched.  A deliberately authored ceiling
(anything other than ``30.0``, e.g. the 180s some installs set by hand in the
YAML draft editor) is left exactly as written.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
import yaml
from alembic import op

revision = "20260722_0074"
down_revision = "20260716_0073"
branch_labels = None
depends_on = None

# The value `system_config.setdefault` stamped; anything else was authored.
_LEGACY_DEFAULT_TIMEOUT_SECONDS = 30.0


def _loads(value: Any) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _strip_legacy_timeout(parsed: Any) -> dict[str, Any] | None:
    """Return the rewritten payload, or ``None`` when nothing should change."""

    if not isinstance(parsed, dict):
        return None
    llm = parsed.get("llm")
    if not isinstance(llm, dict) or "timeout_seconds" not in llm:
        return None
    try:
        current = float(llm["timeout_seconds"])
    except (TypeError, ValueError):
        return None
    if current != _LEGACY_DEFAULT_TIMEOUT_SECONDS:
        return None
    rewritten = dict(parsed)
    rewritten_llm = dict(llm)
    rewritten_llm.pop("timeout_seconds")
    rewritten["llm"] = rewritten_llm
    return rewritten


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT snapshot_id, yaml_raw, parsed_json FROM system_config_snapshots "
            "WHERE category = 'api'"
        )
    ).fetchall()

    skipped: list[str] = []
    for snapshot_id, yaml_raw, parsed_json in rows:
        rewritten = _strip_legacy_timeout(_loads(parsed_json))
        if rewritten is None:
            continue
        # ``parsed_json`` is what the runtime reads (``load_active_config_payload``);
        # ``yaml_raw`` is what the 系统配置 YAML editor shows and re-validates on the
        # operator's next save (``create_draft`` → ``validate_config``).  Cleaning only
        # one of them does not "mostly work": the editor still shows 30.0, and the next
        # save in that category writes it straight back into parsed_json — the ceiling
        # returns with no diagnostic, which is exactly the failure this migration exists
        # to end.  So both columns move together or neither does.
        rewritten_yaml = None
        if isinstance(yaml_raw, str):
            try:
                yaml_payload = yaml.safe_load(yaml_raw)
            except yaml.YAMLError:
                yaml_payload = None
            rewritten_yaml_payload = _strip_legacy_timeout(yaml_payload)
            if rewritten_yaml_payload is not None:
                rewritten_yaml = yaml.safe_dump(
                    rewritten_yaml_payload, allow_unicode=True, sort_keys=False
                )
        if rewritten_yaml is None:
            # The YAML side is unparseable, or declares something other than the legacy
            # 30.0 (i.e. the operator authored it).  Leave the whole row alone so the two
            # columns stay consistent, and name it so the operator can fix it by hand.
            skipped.append(str(snapshot_id))
            continue
        bind.execute(
            sa.text(
                "UPDATE system_config_snapshots SET yaml_raw = :yaml_raw, parsed_json = :parsed_json "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {
                "yaml_raw": rewritten_yaml,
                "parsed_json": json.dumps(rewritten, ensure_ascii=False),
                "snapshot_id": snapshot_id,
            },
        )

    if skipped:
        print(
            "[0074] 这些 api 配置快照的 YAML 与 parsed_json 对不上（YAML 解析失败，或它声明的 "
            f"timeout_seconds 不是遗留默认值 {_LEGACY_DEFAULT_TIMEOUT_SECONDS}），"
            "已整行跳过、未做任何改动，请到「系统配置 → 模型与接入」手工核对："
            + "、".join(skipped)
        )


def downgrade() -> None:
    """No-op by design — this migration is not losslessly reversible.

    A symmetric downgrade would have to put ``llm.timeout_seconds: 30.0`` back on
    exactly the snapshots ``upgrade()`` stripped it from.  Nothing in the schema
    records that: after the upgrade, a snapshot ``upgrade()`` cleaned and a snapshot
    authored later with no ceiling at all are byte-for-byte indistinguishable.

    The earlier implementation stamped 30.0 onto *every* api snapshot missing the key.
    That reintroduces the exact defect this migration exists to remove — a
    machine-written ceiling that was never an authoring decision, cutting off long
    generations with ``LLM_REQUEST_TIMEOUT`` — and it does so on snapshots this
    migration never touched.  Silently corrupting authored config is worse than an
    incomplete downgrade, so this restores nothing.

    An operator who genuinely wants the old ceiling back sets it in the 系统配置
    YAML editor, where it becomes a real authoring decision and survives every
    future run of this migration (only the exact legacy 30.0 is ever touched).
    """
