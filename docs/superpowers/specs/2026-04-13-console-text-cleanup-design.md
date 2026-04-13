# Console Text Cleanup Design

> Date: 2026-04-13
> Target slice: unify residual English and mojibake across the runtime shell UI, related frontend tests, and operator-facing README guidance.

---

## 1. Background

The repository already includes a recent frontend slice described as a pure-Chinese console closeout, but the current tree still shows three classes of text drift:

- user-facing shell and authoring views still contain English labels, notices, loading states, and action text
- several frontend unit and E2E tests still assert against mojibake snapshots or outdated English copy
- the README still describes shell views with stale English-facing names and does not reflect the current authoring surfaces

This slice is a text-and-encoding cleanup only. It is meant to make the shipped UI, the tests that protect it, and the operator docs agree on one readable vocabulary.

---

## 2. Goals

1. Replace residual mojibake in the frontend with readable Chinese copy.
2. Replace residual English UI copy in the shell and authoring views with consistent Chinese labels.
3. Update frontend tests so they assert against real Chinese UI text or against stable structural markers instead of broken encoding snapshots.
4. Sync README sections that describe shell views or operator actions so they match the current Chinese console naming and include the authoring surfaces now present in the app.

---

## 3. Non-Goals

- No API, store, route, or state-flow behavior changes.
- No `data-testid` renames unless a test is currently impossible to express without one.
- No introduction of an i18n framework, translation map, or shared copy registry in this slice.
- No broad rewrite of README technical sections that are unrelated to shell naming or operator-facing workflow descriptions.

---

## 4. Recommended Approach

### 4.1 Option summary

Three possible approaches were considered:

- patch only the visible Vue copy
- patch Vue copy plus README, but leave tests carrying historical mojibake constants
- patch Vue copy, README, and the affected frontend tests together

The recommended option is the third approach because it fully closes the inconsistency without expanding into product logic work.

### 4.2 Why this approach

Leaving tests or docs behind would preserve broken text in the repository even after the visible UI becomes clean. Updating all three layers together keeps the maintenance surface small and makes future copy edits easier to reason about.

---

## 5. Design

### 5.1 Frontend source cleanup

The following frontend surfaces are in scope:

- shell navigation labels
- shell notices and control labels
- author workspace titles, descriptions, buttons, loading states, empty states, and confirmation copy
- author trash titles, descriptions, buttons, loading states, empty states, and confirmation copy
- backend-owned author lifecycle block reasons or status messages that are surfaced verbatim inside those views
- any stray mojibake comments or legacy encoding snapshots that are no longer needed

Implementation rules:

- keep view ids, route ids, store names, and API contract names unchanged
- keep `data-testid` values unchanged unless tests become impossible to express otherwise
- normalize wording to concise product Chinese rather than transliterated or mixed-language phrases

### 5.2 Test cleanup

Frontend tests will be updated in two ways:

- where the test is verifying a real user-visible label, assert the final Chinese text directly
- where the test is really verifying registration or wiring, replace brittle mojibake string snapshots with stable structural assertions

This especially applies to:

- shell navigation registration tests
- author workspace and author trash source tests
- E2E specs that currently assert against mojibake labels or notices

The goal is for the tests to protect intended behavior without freezing broken encoding artifacts.

### 5.3 README cleanup

README changes are limited to operator-facing prose that names shell views or describes how to navigate the console.

Rules:

- update view names to match the cleaned Chinese UI
- include the current authoring surfaces where the README currently lists only runtime/review/index/knowledge/interop views
- leave endpoint literals, command lines, and code identifiers unchanged

### 5.4 Error handling and risk containment

This slice should not create new runtime failure modes because it does not change data flow. The main risk is test churn from over-coupling to exact wording.

To control that risk:

- prefer direct text assertions only where the user truly sees that exact copy
- prefer structural assertions when the wording is incidental to the behavior under test
- avoid opportunistic refactors while touching text-heavy files

---

## 6. Verification

Verification will happen in a narrow, text-focused loop:

1. Add or update failing frontend tests first so the expected Chinese text or non-mojibake assertions are explicit.
2. Update the Vue source and README to satisfy those tests.
3. Run the targeted Vitest files that cover shell registration and authoring views.
4. Run the targeted Playwright author-workspace and author-trash specs if the copy changes affect browser assertions.
5. Review the final diff to confirm no logic or selector churn escaped the intended scope.

Success for this slice means:

- no user-visible mojibake remains in the touched shell surfaces
- targeted tests pass with clear Chinese or stable structural assertions
- README view naming matches the app's current console layout

---

## 7. Scope Boundary

This is the smallest slice that fully closes the text drift:

- source copy
- affected frontend tests
- operator-facing README shell naming

Anything beyond that, including broader documentation translation or a reusable localization system, belongs in a later slice.
