async (page) => {
  const baseUrl = "http://127.0.0.1:5173";
  const loopback = "http://127.0.0.1";
  const apiBase =
    (typeof process !== "undefined" && process.env?.PLAYWRIGHT_API_BASE) ||
    `${loopback}:${(typeof process !== "undefined" && process.env?.PLAYWRIGHT_BACKEND_PORT) || "8000"}`;
  const operatorRef = "qa.three-chapters.real-llm";
  const outDir = "output/playwright/three-chapter-qa";
  const headers = () => ({
    "X-Operator-Ref": operatorRef,
    "X-Idempotency-Key": `qa-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  });
  const events = {
    console: [],
    pageErrors: [],
    requestFailures: [],
    steps: [],
  };
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      events.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => events.pageErrors.push(String(error)));
  page.on("requestfailed", (request) => {
    events.requestFailures.push({
      url: request.url(),
      method: request.method(),
      error: request.failure()?.errorText || "",
    });
  });

  async function step(name, action) {
    const started = Date.now();
    try {
      const result = await action();
      events.steps.push({ name, ok: true, ms: Date.now() - started, result });
      return result;
    } catch (error) {
      events.steps.push({ name, ok: false, ms: Date.now() - started, error: String(error) });
      throw error;
    }
  }

  async function safeScreenshot(name) {
    await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true }).catch(() => null);
  }

  async function clickIfEnabled(locator) {
    if ((await locator.count()) === 0) return false;
    if (await locator.first().isDisabled().catch(() => false)) return false;
    await locator.first().click();
    return true;
  }

  async function getJson(path, options = {}) {
    const response = await page.request.get(`${apiBase}${path}`, {
      headers: { "X-Operator-Ref": operatorRef },
      ...options,
    });
    return response.json();
  }

  async function postJson(path, data = {}, options = {}) {
    const response = await page.request.post(`${apiBase}${path}`, {
      headers: headers(),
      data,
      ...options,
    });
    const body = await response.json().catch(() => null);
    return { status: response.status(), body };
  }

  await page.goto(baseUrl);
  await page.evaluate(
    ({ apiBase, operatorRef }) => {
      localStorage.setItem("novel-system-api-base", apiBase);
      localStorage.setItem("novel-system-operator-ref", operatorRef);
    },
    { apiBase, operatorRef },
  );
  await page.reload();

  const referenceResult = await step("reference learning import/analyze/review/apply", async () => {
    await page.getByTestId("nav-reference").click();
    await page.getByTestId("reference-learning-view").waitFor({ timeout: 30000 });
    await safeScreenshot("reference-initial");

    const importToggle = page.getByTestId("reference-import-toggle");
    if ((await importToggle.count()) && !(await page.getByTestId("reference-import-path").isVisible().catch(() => false))) {
      await importToggle.click();
    }
    await page.getByTestId("reference-import-path").fill("E:/codex/xiaoshuo/codex/frontend/tests/e2e/fixtures/reference-learning.md");
    const pathForm = page.locator("form").filter({ has: page.getByTestId("reference-import-path") });
    await pathForm.locator("input").nth(1).fill("Three Chapter QA Reference Fixture");
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/reference-books/import-path"), { timeout: 30000 }),
      page.getByTestId("reference-import-submit").click(),
    ]);

    const importBooks = await getJson("/api/v1/reference-books");
    const book =
      importBooks.data?.items?.find((item) => item.title === "Three Chapter QA Reference Fixture") ||
      importBooks.data?.items?.find((item) => item.source_path?.includes("reference-learning.md")) ||
      importBooks.data?.items?.[0];
    if (!book?.book_id) throw new Error("reference book not found after import");

    await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/runs`), {
        timeout: 30000,
      }),
      page.getByTestId("reference-start-run").click(),
    ]);
    const startDetail = await getJson(`/api/v1/reference-books/${book.book_id}`);
    const runId = startDetail.data?.latest_run?.run_id;
    if (!runId) throw new Error("reference run did not start");

    const advanceResponse = await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/runs/${runId}/advance`),
        { timeout: 240000 },
      ),
      page.getByTestId("reference-advance-run").click(),
    ]).then(([resp]) => resp.json());
    const findings = advanceResponse.data?.round?.findings || [];
    if (!findings.length) throw new Error("reference advance did not return findings");

    const decisions = [];
    for (let index = 0; index < findings.length; index += 1) {
      const finding = findings[index];
      const reviewId = finding.review?.review_id || finding.review_id;
      if (!reviewId) continue;
      if (index === findings.length - 1) {
        const card = page.getByTestId(`reference-finding-${finding.finding_id}`);
        const rejectInput = card.locator("input.control-input").first();
        if ((await rejectInput.count()) > 0) {
          await rejectInput.fill("QA reject path exercised after enough approvals");
        }
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/reject`), {
            timeout: 30000,
          }),
          page.getByTestId(`reference-reject-${reviewId}`).click(),
        ]);
        decisions.push({ reviewId, decision: "rejected" });
      } else {
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/approve`), {
            timeout: 30000,
          }),
          page.getByTestId(`reference-approve-${reviewId}`).click(),
        ]);
        decisions.push({ reviewId, decision: "approved" });
      }
    }

    const profileResponse = await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/runs/${runId}/advance`),
        { timeout: 240000 },
      ),
      page.getByTestId("reference-advance-run").click(),
    ]).then(([resp]) => resp.json());
    let detail = await getJson(`/api/v1/reference-books/${book.book_id}`);
    const profile =
      profileResponse.data?.profile ||
      (detail.data?.profiles || []).find((item) => item.status === "ready") ||
      detail.data?.profiles?.[0];
    if (!profile?.profile_id) throw new Error("reference profile not created");

    await page.getByTestId("reference-apply-scope").selectOption("chapter");
    await page.getByTestId("reference-apply-scope-ref").fill("CHQA01");
    const applyResponse = await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/profiles/${profile.profile_id}/apply`),
        { timeout: 30000 },
      ),
      page.getByTestId(`reference-apply-${profile.profile_id}`).click(),
    ]).then(([resp]) => resp.json());

    detail = await getJson(`/api/v1/reference-books/${book.book_id}`);
    await safeScreenshot("reference-after-apply");
    return {
      bookId: book.book_id,
      runId,
      findingCount: findings.length,
      decisions,
      profileId: profile.profile_id,
      applyReviewIds: (applyResponse.data?.reviews || []).map((item) => item.review_id),
      coverage: detail.data?.coverage,
    };
  });

  const reviewResult = await step("review inbox approve/release reference apply and inspect human review", async () => {
    await page.getByTestId("nav-review").click();
    await page.getByTestId("review-inbox-view").waitFor({ timeout: 30000 });
    await page.getByTestId("review-filter-status").selectOption("");
    await page.getByTestId("review-filter-refresh").click();
    await page.waitForTimeout(1000);

    const released = [];
    for (const reviewId of referenceResult.applyReviewIds || []) {
      const card = page.getByTestId(`review-card-${reviewId}`);
      await card.scrollIntoViewIfNeeded({ timeout: 30000 }).catch(() => null);
      await clickIfEnabled(page.getByTestId(`review-toggle-payload-${reviewId}`));
      await Promise.all([
        page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/approve`), {
          timeout: 30000,
        }),
        page.getByTestId(`review-approve-${reviewId}`).click(),
      ]);
      await page.waitForTimeout(500);
      await Promise.all([
        page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/release`), {
          timeout: 30000,
        }),
        page.getByTestId(`review-release-${reviewId}`).click(),
      ]);
      released.push(reviewId);
    }

    await page.getByTestId("human-review-filter-event-source").selectOption("");
    await page.getByTestId("human-review-filter-refresh").click();
    await page.waitForTimeout(1000);
    const humanEvents = await getJson("/api/v1/human-review-events?limit=5");
    const firstEventId = humanEvents.data?.items?.[0]?.event_id;
    if (firstEventId) {
      await clickIfEnabled(page.getByTestId(`human-review-toggle-details-${firstEventId}`));
      await clickIfEnabled(page.getByTestId(`human-review-toggle-history-${firstEventId}`));
      await clickIfEnabled(page.getByTestId(`human-review-open-replay-${firstEventId}`));
      await clickIfEnabled(page.getByTestId(`human-review-open-linked-${firstEventId}`));
    }
    await safeScreenshot("review-inbox");
    return { released, inspectedHumanEvent: firstEventId || null };
  });

  const indexResult = await step("index console promotions/recovery/ledger", async () => {
    await page.getByTestId("nav-index").click();
    await page.getByTestId("index-console-view").waitFor({ timeout: 30000 });
    await page.getByTestId("run-due-promotions-button").click();
    await page.waitForResponse((resp) => resp.url().includes("/api/v1/versioning/promotions/due"), { timeout: 30000 }).catch(() => null);
    await page.getByTestId("run-recovery-sweep-button").click();
    await page.waitForResponse((resp) => resp.url().includes("/api/v1/runtime-recovery/sweep"), { timeout: 30000 }).catch(() => null);
    await clickIfEnabled(page.getByTestId("index-toggle-recovery-timeline"));
    await clickIfEnabled(page.getByTestId("index-toggle-target-groups"));
    await clickIfEnabled(page.getByTestId("index-toggle-operator-action"));
    const jobs = await getJson("/api/v1/index/jobs?limit=20");
    const verifyJob = (jobs.data?.items || []).find((item) => item.job_type === "verify");
    if (verifyJob?.job_id) {
      await clickIfEnabled(page.getByTestId(`retry-verify-job-${verifyJob.job_id}`));
      await page.waitForTimeout(1000);
    }
    await safeScreenshot("index-console");
    const ledger = await getJson("/api/v1/index/runtime-ledger?limit=10");
    return {
      sampledJobId: verifyJob?.job_id || null,
      jobCount: jobs.data?.items?.length || 0,
      ledgerCount: ledger.data?.items?.length || 0,
    };
  });

  const interopResult = await step("interop preview/import/export/replay", async () => {
    await page.getByTestId("nav-interop").click();
    await page.getByTestId("interop-center-view").waitFor({ timeout: 30000 });
    const worksheet = `
bundle_id: bundle_interop_three_chapter_qa
scene_id: CHQA01_SC01
chapter_id: CHQA01
hash_contract_version: BSHASH_v1
hash_alg: sha256
execution_mode: P1_scripted
created_by_action: bundle_worksheet_import
snapshot:
  contract_version: BSHASH_v1
  stage_allowlist_name: bundle_build_allowlist_v1
  scene_id: CHQA01_SC01
  chapter_id: CHQA01
  source_version_refs:
    chapter_goal: CHQA01
    scene_card: CHQA01_SC01
    style_rule_set_id: STYLE_QA_THREE_CHAPTERS
  resolved_ref_ids:
    relation_ids: []
    world_rule_ids: []
    open_foreshadow_ids: []
  ordered_injections:
    - slot: chapter_goal
      ref_id: CHQA01
      digest_key: chapter_goal
    - slot: scene_card
      ref_id: CHQA01_SC01
      digest_key: scene_card
    - slot: style_rules
      ref_id: STYLE_QA_THREE_CHAPTERS
      digest_key: style_rule
  inline_digests:
    chapter_goal: first chapter archive-letter clue
    scene_card: Shen Lan receives the archive letter
    style_rule: tactile clue, hidden pressure, visual hook
`.trim();
    await page.getByTestId("interop-worksheet-input").fill(worksheet);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/preview/bundle-worksheet"), { timeout: 30000 }),
      page.getByTestId("interop-preview-button").click(),
    ]);
    await page.getByTestId("interop-preview-summary").waitFor({ timeout: 30000 });
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/import/bundle-worksheet"), { timeout: 30000 }),
      page.getByTestId("interop-import-button").click(),
    ]);
    await page.getByTestId("interop-import-receipt").waitFor({ timeout: 30000 });
    await page.getByTestId("interop-export-bundle-id").fill("bundle_interop_three_chapter_qa");
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/export/bundle-worksheet/bundle_interop_three_chapter_qa"), {
        timeout: 30000,
      }),
      page.getByTestId("interop-export-button").click(),
    ]);
    await page.getByTestId("interop-envelope-panel").waitFor({ timeout: 30000 });
    await page.getByTestId("interop-replay-final-row-id").fill("final_scene_CHQA01_SC01_v5");
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/replay/final-scene/final_scene_CHQA01_SC01_v5"), {
        timeout: 30000,
      }),
      page.getByTestId("interop-replay-final-button").click(),
    ]);
    await page.getByTestId("interop-replay-receipt").waitFor({ timeout: 30000 });
    await safeScreenshot("interop-center");
    return { bundleId: "bundle_interop_three_chapter_qa", replayedFinalRowId: "final_scene_CHQA01_SC01_v5" };
  });

  const trashResult = await step("author trash move/restore/purge separate records", async () => {
    const suffix = `${Date.now()}`.slice(-6);
    const chapterId = `CHQAT${suffix}`;
    const sceneA = `${chapterId}_SC01`;
    const sceneB = `${chapterId}_SC02`;
    await page.getByTestId("nav-author").click();
    await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
    await page.getByTestId("author-new-chapter-button").click();
    await page.getByTestId("author-chapter-id").fill(chapterId);
    await page.getByTestId("author-chapter-scene-count").fill("2");
    await page.getByTestId("author-chapter-goal").fill("QA trash lifecycle chapter");
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/chapters/${chapterId}/goal`), { timeout: 30000 }),
      page.getByTestId("author-save-chapter-button").click(),
    ]);
    for (const sceneId of [sceneA, sceneB]) {
      await page.getByTestId("author-new-scene-button").click();
      await page.getByTestId("author-scene-id").fill(sceneId);
      await page.getByTestId("author-scene-goal").fill(`QA trash lifecycle scene ${sceneId}`);
      await Promise.all([
        page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/card`), { timeout: 30000 }),
        page.getByTestId("author-save-scene-button").click(),
      ]);
    }

    await page.getByTestId(`author-scene-select-${sceneB}`).check();
    page.once("dialog", (dialog) => dialog.accept());
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/scenes/trash"), { timeout: 30000 }),
      page.getByTestId("author-trash-selected-scenes-button").click(),
    ]);

    await page.getByTestId("nav-trash").click();
    await page.getByTestId("author-trash-view").waitFor({ timeout: 30000 });
    await page.getByTestId(`author-trash-scene-select-${sceneB}`).check();
    page.once("dialog", (dialog) => dialog.accept());
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/scenes/restore"), { timeout: 30000 }),
      page.getByTestId("author-trash-restore-scenes-button").click(),
    ]);

    await page.getByTestId("nav-author").click();
    await page.getByTestId(`author-chapter-select-for-trash-${chapterId}`).check();
    page.once("dialog", (dialog) => dialog.accept());
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/chapters/trash"), { timeout: 30000 }),
      page.getByTestId("author-trash-selected-chapters-button").click(),
    ]);

    await page.getByTestId("nav-trash").click();
    await page.getByTestId(`author-trash-chapter-select-${chapterId}`).check();
    page.once("dialog", (dialog) => dialog.accept());
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/chapters/purge"), { timeout: 30000 }),
      page.getByTestId("author-trash-purge-chapters-button").click(),
    ]);
    await safeScreenshot("author-trash");
    return { chapterId, restoredSceneId: sceneB, purgedChapter: chapterId };
  });

  const configResult = await step("system config probes/eval/export/style review", async () => {
    await page.getByTestId("nav-config").click();
    await page.getByTestId("system-config-view").waitFor({ timeout: 30000 });
    await page.getByTestId("config-refresh").click();
    await page.waitForTimeout(1000);
    await page.getByTestId("config-api-base-probe").click();
    await page.waitForTimeout(1000);
    const providerRow = page.getByTestId("config-llm-provider-row-local_qwen3");
    if ((await providerRow.count()) > 0) {
      await providerRow.locator("button").last().click();
      await page.waitForTimeout(1500);
    }
    await page.getByTestId("config-dashboard-tab-routing").click();
    await clickIfEnabled(page.getByTestId("config-llm-node-routes-save"));
    await page.waitForTimeout(1000);
    await page.getByTestId("config-dashboard-tab-validation").click();
    await clickIfEnabled(page.getByTestId("config-llm-node-routes-save-validation"));
    await page.waitForTimeout(1000);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/literary-eval/run"), { timeout: 60000 }),
      page.getByTestId("config-literary-eval-run").click(),
    ]);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/literary-eval/run"), { timeout: 240000 }),
      page.getByTestId("config-literary-eval-run-live").click(),
    ]);
    await page.getByTestId("config-literary-eval-summary").waitFor({ timeout: 30000 });

    await page.getByTestId("config-dashboard-tab-advanced").click();
    await page.getByTestId("config-category-api").click();
    await page.getByTestId("config-export").click();
    await page.getByTestId("config-export-yaml").waitFor({ timeout: 30000 });
    await page.getByTestId("config-style-profile-sample").fill(
      "雨声先压低了走廊的光，人物只用一个停顿暴露犹豫；句子短，物件触感先于解释。",
    );
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/style-profile/extract"), { timeout: 120000 }),
      page.getByTestId("config-style-profile-extract").click(),
    ]);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/style-profile/review-candidate"), {
        timeout: 30000,
      }),
      page.getByTestId("config-style-profile-submit").click(),
    ]);
    await page.getByTestId("config-style-profile-review").waitFor({ timeout: 30000 });
    await safeScreenshot("system-config");
    const liveEval = await postJson("/api/v1/literary-eval/run", { mode: "live" }, { timeout: 240000 }).catch((error) => ({
      error: String(error),
    }));
    return {
      exportedCategory: "api",
      styleReviewText: await page.getByTestId("config-style-profile-review").textContent().catch(() => ""),
      liveEvalStatus: liveEval.status || null,
      liveEvalOk: liveEval.body?.ok ?? null,
    };
  });

  const chapterStatuses = {};
  for (const chapterId of ["CHQA01", "CHQA02", "CHQA03"]) {
    chapterStatuses[chapterId] = (await getJson(`/api/v1/chapters/${chapterId}/status`)).data;
  }
  await safeScreenshot("final-state");

  return {
    referenceResult,
    reviewResult,
    indexResult,
    interopResult,
    trashResult,
    configResult,
    chapterStatuses: Object.fromEntries(
      Object.entries(chapterStatuses).map(([chapterId, status]) => [
        chapterId,
        {
          finalMemory: status?.chapter_runtime?.last_final_memory_row_id || null,
          aggregateBlockReason: status?.chapter_runtime?.aggregate_block_reason || null,
          passedSceneCount: status?.chapter_runtime?.chapter_passed_scene_count || 0,
          manualHoldReason: status?.chapter_runtime?.manual_hold_reason || null,
        },
      ]),
    ),
    events,
  };
}
