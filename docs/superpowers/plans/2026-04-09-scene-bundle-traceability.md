# Scene Bundle Traceability Implementation Plan

**Status:** implemented

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real version-backed `voice/relation` sources for scene bundle construction and fail scene runs when those traceable sources are missing.

**Architecture:** Introduce lightweight versioned `voice_profiles` and `relation_profiles` tables, teach the resolver to load the active version row for each logical source, and update bundle construction so worksheet snapshots record row/version provenance instead of placeholder digests.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest

---

## File Structure

- `backend/src/novel_system/db/models.py`
  Add `VoiceProfile` and `RelationProfile`.
- `backend/alembic/versions/20260409_0002_bundle_traceability_sources.py`
  Persist the new schema.
- `backend/src/novel_system/services/resolver.py`
  Resolve logical IDs and active version rows.
- `backend/src/novel_system/services/bundle_builder.py`
  Consume active source rows, enrich snapshot refs, and fail when required sources are missing.
- `backend/src/novel_system/tools/seed_demo.py`
  Seed active voice/relation rows for the demo lane.
- `backend/tests/test_orchestrator_flow.py`
  Add red tests for traceability and missing-source failures.
- `backend/tests/test_seed_demo.py`
  Add coverage for seeded voice/relation source rows.

---

### Task 1: Red tests for bundle provenance and missing-source failures

**Files:**
- Modify: `backend/tests/test_orchestrator_flow.py`
- Modify: `backend/tests/test_seed_demo.py`

- [x] **Step 1: Write the failing provenance and failure-path tests**

```python
def test_run_full_scene_records_voice_and_relation_bundle_provenance(client) -> None:
    seed_story(client)

    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-provenance"},
    )

    assert response.status_code == 200
    bundle_id = response.json()["data"]["current_bundle_id"]
    worksheet = client.get(f"/api/v1/interop/export/bundle-worksheet/{bundle_id}")
    snapshot = worksheet.json()["data"]["snapshot"]

    assert snapshot["source_version_refs"]["voice_profile_id"] == "VOICE_CHAR_A"
    assert snapshot["source_version_refs"]["voice_profile_row_id"] == "voice_profile_VOICE_CHAR_A_v1"
    assert snapshot["source_version_refs"]["voice_profile_version"] == 1
    assert snapshot["source_version_refs"]["relation_profile_id"] == "REL_CHAR_A_CHAR_B"
    assert snapshot["source_version_refs"]["relation_profile_row_id"] == "relation_profile_REL_CHAR_A_CHAR_B_v1"
    assert snapshot["source_version_refs"]["relation_profile_version"] == 1
    assert snapshot["inline_digests"]["voice_card"] == "short clipped lines; pressure makes the tone harder"
    assert snapshot["inline_digests"]["relation_card"] == "reunion tension; B knows slightly more than A"


def test_run_full_scene_fails_when_voice_profile_missing(client, session) -> None:
    seed_story(client)
    session.query(VoiceProfile).delete()
    session.commit()

    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-missing-voice"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUNDLE_SOURCE_MISSING"


def test_seed_demo_creates_traceable_voice_and_relation_profiles(session) -> None:
    seed_demo(session)

    voice = session.get(VoiceProfile, "voice_profile_VOICE_CHAR_A_v1")
    relation = session.get(RelationProfile, "relation_profile_REL_CHAR_A_CHAR_B_v1")

    assert voice is not None and voice.active_flag == 1
    assert relation is not None and relation.active_flag == 1
```

- [x] **Step 2: Run the targeted tests to verify they fail**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_seed_demo.py -q`
Expected: FAIL because the new tables, seed rows, and bundle provenance fields do not exist yet.

---

### Task 2: Add lightweight versioned source tables

**Files:**
- Modify: `backend/src/novel_system/db/models.py`
- Create: `backend/alembic/versions/20260409_0002_bundle_traceability_sources.py`

- [x] **Step 1: Add the new SQLAlchemy models**

```python
class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    voice_profile_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    character_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class RelationProfile(Base):
    __tablename__ = "relation_profiles"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    relation_profile_id: Mapped[str] = mapped_column(String)
    left_character_id: Mapped[str] = mapped_column(String)
    right_character_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)
```

- [x] **Step 2: Add the Alembic migration**

```python
"""bundle traceability sources

Revision ID: 20260409_0002
Revises: 20260408_0001
Create Date: 2026-04-09
"""

revision = "20260409_0002"
down_revision = "20260408_0001"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["voice_profiles"], Base.metadata.tables["relation_profiles"]])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["relation_profiles"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["voice_profiles"].drop(bind=bind, checkfirst=True)
```

- [x] **Step 3: Re-run the targeted tests**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_seed_demo.py -q`
Expected: FAIL because runtime services still do not read or seed the new source rows.

---

### Task 3: Resolve active source rows in bundle construction

**Files:**
- Modify: `backend/src/novel_system/services/resolver.py`
- Modify: `backend/src/novel_system/services/bundle_builder.py`

- [x] **Step 1: Upgrade the resolver to load active version rows**

```python
class Resolver:
    def resolve_voice_profile_id(self, scene: SceneCard) -> str | None:
        if scene.pov_character_id:
            return f"VOICE_{scene.pov_character_id}"
        return None

    def resolve_active_voice_profile(self, session: Session, scene: SceneCard) -> VoiceProfile | None:
        profile_id = self.resolve_voice_profile_id(scene)
        if profile_id is None:
            return None
        return session.execute(
            select(VoiceProfile)
            .where(VoiceProfile.voice_profile_id == profile_id, VoiceProfile.active_flag == 1)
            .order_by(VoiceProfile.version.desc())
        ).scalars().first()
```

- [x] **Step 2: Make bundle building record provenance and fail on missing required sources**

```python
voice_profile = self.resolver.resolve_active_voice_profile(self.session, scene)
if scene.pov_character_id and voice_profile is None:
    raise DomainError("BUNDLE_SOURCE_MISSING", f"active voice profile missing for {scene.pov_character_id}", status_code=409)

if voice_profile:
    source_version_refs["voice_profile_id"] = voice_profile.voice_profile_id
    source_version_refs["voice_profile_row_id"] = voice_profile.row_id
    source_version_refs["voice_profile_version"] = voice_profile.version
    ordered_injections.append({"slot": "pov_voice", "ref_id": voice_profile.voice_profile_id, "digest_key": "voice_card"})
    inline_digests["voice_card"] = voice_profile.content
```

- [x] **Step 3: Re-run the targeted tests**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_seed_demo.py -q`
Expected: FAIL because the seed path still does not populate the new source rows.

---

### Task 4: Seed traceable source rows for demo and test helpers

**Files:**
- Modify: `backend/src/novel_system/tools/seed_demo.py`
- Modify: `backend/tests/test_orchestrator_flow.py`

- [x] **Step 1: Seed active voice/relation rows in the demo tool and test helper**

```python
voice = session.get(VoiceProfile, "voice_profile_VOICE_CHAR_A_v1")
if voice is None:
    session.add(
        VoiceProfile(
            row_id="voice_profile_VOICE_CHAR_A_v1",
            voice_profile_id="VOICE_CHAR_A",
            version=1,
            character_id="CHAR_A",
            content="short clipped lines; pressure makes the tone harder",
            active_flag=1,
            source_note="demo baseline",
        )
    )
```

```python
relation = session.get(RelationProfile, "relation_profile_REL_CHAR_A_CHAR_B_v1")
if relation is None:
    session.add(
        RelationProfile(
            row_id="relation_profile_REL_CHAR_A_CHAR_B_v1",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            version=1,
            content="reunion tension; B knows slightly more than A",
            active_flag=1,
            source_note="demo baseline",
        )
    )
```

- [x] **Step 2: Re-run the targeted tests**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_seed_demo.py -q`
Expected: PASS

---

### Task 5: Run backend regression verification

**Files:**
- Modify: `docs/superpowers/specs/2026-04-09-scene-bundle-traceability-design.md`
- Modify: `docs/superpowers/plans/2026-04-09-scene-bundle-traceability.md`
- Modify: `backend/src/novel_system/db/models.py`
- Modify: `backend/src/novel_system/services/resolver.py`
- Modify: `backend/src/novel_system/services/bundle_builder.py`
- Modify: `backend/src/novel_system/tools/seed_demo.py`
- Modify: `backend/tests/test_orchestrator_flow.py`
- Modify: `backend/tests/test_seed_demo.py`
- Create: `backend/alembic/versions/20260409_0002_bundle_traceability_sources.py`

- [x] **Step 1: Run the backend regression slice**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_seed_demo.py tests/test_hash_engine.py tests/test_acceptance_flow.py -q`
Expected: PASS on the targeted backend bundle/replay/demo coverage.

- [x] **Step 2: Run the Windows-safe backend lane**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1 -BackendOnly`
Expected: PASS with all non-`chroma_integration` backend tests green.