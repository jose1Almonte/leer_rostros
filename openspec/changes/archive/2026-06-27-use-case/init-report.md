# SDD Init Report — `use-case` Change

**Phase**: sdd-init  
**Status**: ✅ complete  
**Date**: 2026-06-27  
**Project**: reencuentros  
**Change**: use-case  

---

## Executive Summary

Initialized SDD context for the `use-case` change, which will extract use case modules per flow from `app/main.py`, making endpoints thin HTTP adapters, and refactor `PersonaRepository.add` to accept a `PersonaBase` domain object instead of a raw dict. The prior `core-domain` change (2026-06-27) is archived under `openspec/changes/archive/2026-06-27-core-domain/` and delivered: MatchingPolicy, MenoresPrivacy, PersonaBase/Estado/Foto domain entities, PersonaRepository with all SQL ownership, JWT+bcrypt auth, moderation filter, multi-embedding support, 22 passing tests with 100% domain coverage, v0 dead-code cleanup, and documentation rewrite. The codebase is now well-structured with clean domain/repository layers, and the current `app/main.py` (515 lines) is the natural next target for use case extraction. Config YAML updated with `active_change: use-case` and corrected stack metadata (face_model → buffalo_l, match_threshold → 0.55). Project context updated to reflect current post-core-domain architecture.

## Artifacts Created / Updated

| Path | Action |
|------|--------|
| `openspec/config.yaml` | **Updated** — set `active_change: use-case`; corrected stack metadata to post-core-domain state |
| `openspec/project.md` | **Updated** — rewrote to reflect current architecture: InsightFace buffalo_l, domain/repository layers, all 8 endpoints, JWT auth, 22 tests, removed core-domain section, added use-case scope |
| `openspec/changes/use-case/.gitkeep` | **Created** — placeholder for use-case change artifacts |
| `openspec/changes/use-case/init-report.md` | **Created** — this report |

## Inspection Summary

### Current Architecture (post-core-domain)

```
app/
  main.py              # 515 lines — endpoints with business logic still inline
  domain/
    __init__.py        # Barrel — MatchingPolicy, MenoresPrivacy, PersonaBase, Estado, Foto
    matching.py        # 52 lines — MatchingPolicy dataclass (threshold, bands, sigmoid %)
    privacy.py         # 31 lines — MenoresPrivacy function (masks minors at response boundary)
    persona.py         # 49 lines — Estado enum, Foto dataclass, PersonaBase Pydantic model
  repositories/
    __init__.py        # Barrel — PersonaRepository
    persona.py         # 304 lines — All SQL for personas + persona_embeddings
  auth.py              # JWT + bcrypt, admins table, get_current_admin dependency
  cli.py               # CLI for admin management (create/delete/password/activate/list)
  schemas.py           # Pydantic: Candidato, PersonaAdmin, AlertaFamiliar, LoginBody, etc.
  config.py            # pydantic-settings, match_threshold=0.55, JWT config, sigmoid params
  database.py          # init_db() with pgvector, HNSW, admins table, advisory lock
  faces.py             # InsightFace buffalo_l: detection + embedding + augmentations
  storage.py           # Spaces (S3) or local fallback
  schemas.py           # Pydantic models: Candidato, PersonaAdmin, AlertaFamiliar, etc.
tests/
  conftest.py          # Fixtures: client (TestClient + auth override), policy, admin, tokens
  domain/
    test_matching.py   # 14 tests (100% coverage)
    test_privacy.py    # 8 tests (100% coverage)
```

### What `core-domain` Delivered (archived)

- ✅ `MatchingPolicy` — single source of truth for threshold, confidence bands, sigmoid percentage
- ✅ `MenoresPrivacy` — masks minor names in ALL 4 regular endpoints (public + admin)
- ✅ `PersonaBase` / `Estado` / `Foto` — domain entity layer
- ✅ `PersonaRepository` — owns all SQL for personas + persona_embeddings; no inline SQL in main.py
- ✅ JWT (HS256) + bcrypt auth with `admins` table
- ✅ Multi-embeddings per photo (base + ±15° rotations)
- ✅ Moderation filter (moderacion = 'aprobada' for public searches)
- ✅ 22 passing tests, 100% domain coverage
- ✅ AlertaFamiliar privacy bug fixed; data preservation fix (names stored, not nulled)
- ✅ v0 dead-code deleted; docs rewritten
- ⚠️ Repository tests not implemented (design said optional — requires live PostgreSQL+pgvector)

### What `use-case` Targets

- **Candidate 1**: Extract use case module per flow from `app/main.py`
- **Candidate 5-deepening**: `PersonaRepository.add` accepts `PersonaBase` (not dict); use case builds the domain object
- **NOT in scope**: FaceEmbedder seam (Candidate 4), cross-match module (Candidate 7), repository integration tests, endpoint integration tests

### Key Findings from Inspection

1. **`app/main.py` (515 lines)** — still has validation, dict construction, business flow, and response mapping all inline. The domain logic (matching, privacy) has been extracted, but the orchestration layer remains. This is the prime target for use-case extraction.

2. **`PersonaRepository.add` accepts `dict`, not `PersonaBase`** — the design from core-domain originally planned for `PersonaBase` acceptance but kept dict for pragmatic reasons. The `use-case` change deepens this: the use case builds a `PersonaBase`, and the repo accepts it.

3. **Test infrastructure exists** — `conftest.py` with client/policy/admin/token fixtures, 22 tests in `tests/domain/`. In-memory fakes for use-case testing are straightforward to add using these fixtures.

4. **`faces.embedding_from_bytes` and `faces.embeddings_from_bytes` are the current interface** — both are concrete functions on the `app.faces` module. No abstract seam exists yet. Use-case tests will need to mock these (the matching tests already mock `faces.distance_to_confidence` via `monkeypatch`).

5. **`openspec/config.yaml` stack metadata was stale** — `face_model: "Facenet512"` and `match_threshold: 0.50` were from the pre-core-domain init. Updated to `buffalo_l` and `0.55`.

6. **`.atl/skill-registry.md` exists** — auto-generated by gentle-pi, 24899 bytes. Present, not regenerated.

## Config YAML Summary

| Field | Value | Notes |
|-------|-------|-------|
| project | reencuentros | |
| active_change | use-case | newly set |
| stack.face_model | buffalo_l | corrected from "Facenet512" |
| stack.match_threshold | 0.55 | corrected from 0.50 |
| strict_tdd | false | tests-junto-al-codigo |
| test_command | pytest | |
| execution_mode | interactive | |
| artifact_store | openspec | |
| chained_pr_strategy | auto-forecast | |
| review_budget_lines | 800 | |
| preflight.interactive | true | |
| preflight.phase_gate | true | |
| preflight.testing_discipline | tests-junto-al-codigo | |

## Next Recommended Phase

**sdd-explore** — The explore phase should:

1. Deep-dive into `app/main.py` to map all inline validation, business flow, dict construction, and response mapping
2. Map the exact `PersonaBase` → repo → dict → Pydantic chains
3. Document the seam strategy for `FaceEmbedder` (future change, but understanding the current coupling helps the use-case design)
4. Evaluate in-memory fake approaches for PersonaRepository and FaceEmbedder
5. Assess whether the cross-flow alert logic (currently in `main.py:311-321`) should move into the use case layer or stay as a separate module

## Risks

| Risk | Severity | Description |
|------|----------|-------------|
| Use case boundary ambiguity | medium | Endpoints currently mix validation, dict building, business orchestration, and response construction. Clear boundary definition is critical — explore phase should audit each endpoint flow line by line. |
| PersonaBase → repo coupling | medium | `PersonaRepository.add` currently takes a dict+procesadas tuple. Changing to `PersonaBase` requires updating all call sites (2: buscados + encontrados) and the internal `_row_to_candidato_dict` / `_row_to_admin_dict` mappings. |
| FaceEmbedder mock required | medium | Use case tests need to mock `faces.embeddings_from_bytes` and `faces.embedding_from_bytes`. The matching tests already mock `faces.distance_to_confidence` via monkeypatch — pattern exists. |
| Repository tests still at 0% | low | Defer to future change. Use-case tests can use in-memory fakes. |
| Dict → PersonaBase → dict round-trip | low | If the use case builds PersonaBase and passes to repo, but the repo still returns dicts (from `_row_to_candidato_dict`), there's a type inconsistency at the response boundary. Design should clarify whether the repo returns domain objects or the use case maps them. |

## Skill Resolution

- **Resolution mode**: `paths-injected`
- **Registry**: `.atl/skill-registry.md` — present (24899 bytes), not regenerated
- **Skills loaded**: None — SDD init is context-and-config only
- **Fallback**: Not needed — all skill paths were injected via project_instructions

---

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Inspected full project state: read archived core-domain artifacts (proposal.md, design.md, verify-report.md, archive-report.md), all current source files (main.py, domain/*, repositories/*, auth.py, cli.py, config.py, database.py, faces.py, storage.py, schemas.py, tests/*), and documentation (CLAUDE.md, AGENTS.md, ARQUITECTURA.md). Updated config.yaml with active_change: use-case and corrected stack metadata. Updated project.md to reflect post-core-domain architecture. Created openspec/changes/use-case/ directory. All findings documented with file paths and severity."
    }
  ],
  "changedFiles": [
    "openspec/config.yaml",
    "openspec/project.md",
    "openspec/changes/use-case/.gitkeep",
    "openspec/changes/use-case/init-report.md"
  ],
  "testsAddedOrUpdated": [],
  "commandsRun": [
    {
      "command": "mkdir -p openspec/changes/use-case",
      "result": "passed",
      "summary": "Created change directory for active_change: use-case"
    },
    {
      "command": "Read all archived core-domain artifacts and current source files",
      "result": "passed",
      "summary": "Comprehensive inspection of 20+ files completed"
    }
  ],
  "validationOutput": [
    "openspec/config.yaml: YAML clean, active_change=use-case set, stack metadata corrected",
    "openspec/project.md: rewritten to reflect current post-core-domain state (InsightFace buffalo_l, domain/repository layers, 8 endpoints, JWT auth, 22 tests)",
    "openspec/changes/use-case/: created with .gitkeep placeholder",
    "Core-domain archive verified: 22/22 tests pass, 100% domain coverage, all requirements implemented",
    "No staged files — all changes are SDD infrastructure only"
  ],
  "residualRisks": [
    "Stack metadata in config.yaml was stale (Facenet512/0.50) from pre-core-domain init — corrected to buffalo_l/0.55",
    "PersonaRepository.add still accepts dict, not PersonaBase — use-case change will refactor this",
    "Repository layer at 0% test coverage (requires live PostgreSQL+pgvector)",
    "app/main.py at 515 lines with inline orchestration — use-case extraction will reduce this significantly",
    "No FaceEmbedder seam exists yet — use-case tests will need to mock concrete functions via monkeypatch"
  ],
  "noStagedFiles": true,
  "diffSummary": "Updated openspec/config.yaml (active_change + stack metadata), rewrote openspec/project.md for post-core-domain state, created openspec/changes/use-case/ directory with .gitkeep and init-report.md. No code changes.",
  "reviewFindings": [
    "no-blockers: All SDD infrastructure correctly initialized for use-case change",
    "info: config.yaml face_model and match_threshold were stale (Facenet512/0.50 from pre-core-domain era) — corrected to buffalo_l/0.55",
    "info: project.md had stale references to DeepFace/Facenet512 and core-domain as active change — fully updated",
    "info: 515-line main.py is the prime extraction target — endpoint flows well-documented for use-case audit",
    "info: Test fixtures (client, policy, admin, admin_token, admin_headers) available for use-case unit tests",
    "info: .atl/skill-registry.md exists (24899 bytes) — not regenerated"
  ],
  "manualNotes": "The archived core-domain change is complete and verified (22/22 tests, 100% domain coverage, all spec requirements met). The use-case change builds on this foundation. The project is well-structured with clean domain/repository layers, making use-case extraction a natural next step. The explore phase should map each endpoint flow line-by-line to define clear use case boundaries."
}
```
