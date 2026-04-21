async (page) => {
  const loopback = "http://127.0.0.1";
  const apiBase =
    (typeof process !== "undefined" && process.env?.PLAYWRIGHT_API_BASE) ||
    `${loopback}:${(typeof process !== "undefined" && process.env?.PLAYWRIGHT_BACKEND_PORT) || "8000"}`;
  const operatorRef = "qa.three-chapters.real-llm";
  const outDir = "output/playwright/three-chapter-qa";
  const result = { steps: [], console: [], pageErrors: [], requestFailures: [] };
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) result.console.push({ type: message.type(), text: message.text() });
  });
  page.on("pageerror", (error) => result.pageErrors.push(String(error)));
  page.on("requestfailed", (request) =>
    result.requestFailures.push({ url: request.url(), method: request.method(), error: request.failure()?.errorText || "" }),
  );
  const idKey = () => `qa-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const headers = () => ({ "X-Operator-Ref": operatorRef, "X-Idempotency-Key": idKey() });
  const get = async (path) =>
    (await page.request.get(`${apiBase}${path}`, { headers: { "X-Operator-Ref": operatorRef } })).json();
  const post = async (path, data = {}) =>
    (await page.request.post(`${apiBase}${path}`, { headers: headers(), data })).json();
  const shot = async (name) => page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true }).catch(() => null);
  const clickIfEnabled = async (locator) => {
    if (!(await locator.count())) return false;
    if (await locator.first().isDisabled().catch(() => false)) return false;
    await locator.first().click();
    return true;
  };
  async function step(name, fn) {
    const started = Date.now();
    try {
      const data = await fn();
      result.steps.push({ name, ok: true, ms: Date.now() - started, data });
      return data;
    } catch (error) {
      result.steps.push({ name, ok: false, ms: Date.now() - started, error: String(error) });
      throw error;
    }
  }

  await page.evaluate(
    ({ apiBase, operatorRef }) => {
      localStorage.setItem("novel-system-api-base", apiBase);
      localStorage.setItem("novel-system-operator-ref", operatorRef);
    },
    { apiBase, operatorRef },
  );

  const reference = await step("reference decisions, profile, apply to CHQA01", async () => {
    await page.getByTestId("nav-reference").click();
    await page.getByTestId("reference-learning-view").waitFor({ timeout: 30000 });
    const books = await get("/api/v1/reference-books");
    const book = books.data.items.find((item) => item.title === "Three Chapter QA Reference Fixture");
    if (!book) throw new Error("reference fixture book missing");
    let detail = await get(`/api/v1/reference-books/${book.book_id}`);
    const runId = detail.data.latest_run.run_id;
    const findings = detail.data.latest_round.findings;
    const decisions = [];
    for (let index = 0; index < findings.length; index += 1) {
      const finding = findings[index];
      const reviewId = finding.review.review_id;
      if (finding.status !== "pending" && finding.review.status !== "pending") {
        decisions.push({ reviewId, skipped: finding.review.status || finding.status });
        continue;
      }
      if (index === findings.length - 1) {
        const card = page.getByTestId(`reference-finding-${finding.finding_id}`);
        await card.locator("input.control-input").first().fill("QA exercised reject path after enough coverage");
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/reject`), { timeout: 30000 }),
          page.getByTestId(`reference-reject-${reviewId}`).click(),
        ]);
        decisions.push({ reviewId, decision: "rejected" });
      } else {
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/approve`), { timeout: 30000 }),
          page.getByTestId(`reference-approve-${reviewId}`).click(),
        ]);
        decisions.push({ reviewId, decision: "approved" });
      }
    }
    await page.waitForTimeout(1000);
    const profileResponse = await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/runs/${runId}/advance`), {
        timeout: 300000,
      }),
      page.getByTestId("reference-advance-run").click(),
    ]).then(([resp]) => resp.json());
    detail = await get(`/api/v1/reference-books/${book.book_id}`);
    const profile =
      profileResponse.data.profile ||
      detail.data.profiles.find((item) => item.status === "ready") ||
      detail.data.profiles[0];
    if (!profile?.profile_id) throw new Error("reference profile missing");
    await page.getByTestId("reference-apply-scope").selectOption("chapter");
    await page.getByTestId("reference-apply-scope-ref").fill("CHQA01");
    const apply = await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().endsWith(`/api/v1/reference-books/${book.book_id}/profiles/${profile.profile_id}/apply`),
        { timeout: 30000 },
      ),
      page.getByTestId(`reference-apply-${profile.profile_id}`).click(),
    ]).then(([resp]) => resp.json());
    await shot("reference-after-profile-apply");
    return {
      bookId: book.book_id,
      runId,
      decisions,
      profileId: profile.profile_id,
      applyReviewIds: (apply.data.reviews || []).map((item) => item.review_id),
      coverage: (await get(`/api/v1/reference-books/${book.book_id}`)).data.coverage,
    };
  });

  const config = await step("system config probes, live eval, export, style review", async () => {
    await page.getByTestId("nav-config").click();
    await page.getByTestId("system-config-view").waitFor({ timeout: 30000 });
    await page.getByTestId("config-refresh").click();
    await page.waitForTimeout(700);
    await page.getByTestId("config-api-base-probe").click();
    await page.waitForTimeout(700);
    const providerRow = page.getByTestId("config-llm-provider-row-local_qwen3");
    if (await providerRow.count()) {
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
    const liveResponse = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/literary-eval/run"), { timeout: 300000 }),
      page.getByTestId("config-literary-eval-run-live").click(),
    ]).then(([resp]) => resp.json());
    await page.getByTestId("config-dashboard-tab-advanced").click();
    await page.getByTestId("config-category-api").click();
    await page.getByTestId("config-export").click();
    await page.getByTestId("config-export-yaml").waitFor({ timeout: 30000 });
    await page
      .getByTestId("config-style-profile-sample")
      .fill("雨声压低走廊灯光，人物先触摸信纸再回答；短句制造停顿，解释被推迟到动作之后。");
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/style-profile/extract"), { timeout: 180000 }),
      page.getByTestId("config-style-profile-extract").click(),
    ]);
    const styleReviewResponse = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes("/api/v1/style-profile/review-candidate"), { timeout: 30000 }),
      page.getByTestId("config-style-profile-submit").click(),
    ]).then(([resp]) => resp.json());
    await page.getByTestId("config-style-profile-review").waitFor({ timeout: 30000 });
    await shot("system-config-complete");
    return {
      liveEvalSummary: liveResponse.data?.summary || null,
      styleReviewId: styleReviewResponse.data?.review_id || null,
      exportedCategory: "api",
    };
  });

  const reviewIds = [...reference.applyReviewIds, config.styleReviewId].filter(Boolean);
  const review = await step("review inbox approve/release pending generated reviews", async () => {
    await page.getByTestId("nav-review").click();
    await page.getByTestId("review-inbox-view").waitFor({ timeout: 30000 });
    await page.getByTestId("review-filter-status").selectOption("");
    await page.getByTestId("review-filter-refresh").click();
    await page.waitForTimeout(1500);
    const released = [];
    for (const reviewId of reviewIds) {
      const item = (await get(`/api/v1/review-items?review_id=${encodeURIComponent(reviewId)}`)).data.items?.[0];
      if (!item) continue;
      await page.getByTestId(`review-card-${reviewId}`).scrollIntoViewIfNeeded({ timeout: 30000 }).catch(() => null);
      await clickIfEnabled(page.getByTestId(`review-toggle-payload-${reviewId}`));
      if (item.status === "pending") {
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/approve`), { timeout: 30000 }),
          page.getByTestId(`review-approve-${reviewId}`).click(),
        ]);
      }
      await page.waitForTimeout(700);
      const approved = (await get(`/api/v1/review-items?review_id=${encodeURIComponent(reviewId)}`)).data.items?.[0];
      if (approved?.materialize_status === "succeeded") {
        await Promise.all([
          page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/release`), { timeout: 30000 }),
          page.getByTestId(`review-release-${reviewId}`).click(),
        ]);
        released.push(reviewId);
      }
    }
    await page.getByTestId("human-review-filter-event-source").selectOption("");
    await page.getByTestId("human-review-filter-refresh").click();
    await page.waitForTimeout(1000);
    const humanEvents = await get("/api/v1/human-review-events?limit=5");
    const firstEventId = humanEvents.data.items?.[0]?.event_id || null;
    if (firstEventId) {
      await clickIfEnabled(page.getByTestId(`human-review-toggle-details-${firstEventId}`));
      await clickIfEnabled(page.getByTestId(`human-review-toggle-history-${firstEventId}`));
      await clickIfEnabled(page.getByTestId(`human-review-open-linked-${firstEventId}`));
    }
    await shot("review-inbox-complete");
    return { released, inspectedHumanEvent: firstEventId };
  });

  const index = await step("index console promotions, recovery, job views", async () => {
    await page.getByTestId("nav-index").click();
    await page.getByTestId("index-console-view").waitFor({ timeout: 30000 });
    await page.getByTestId("run-due-promotions-button").click();
    await page.waitForTimeout(1500);
    await page.getByTestId("run-recovery-sweep-button").click();
    await page.waitForTimeout(1500);
    for (const testId of ["index-toggle-recovery-timeline", "index-toggle-target-groups", "index-toggle-operator-action"]) {
      await clickIfEnabled(page.getByTestId(testId));
    }
    const jobs = await get("/api/v1/index/jobs?limit=20");
    const verifyJob = jobs.data.items.find((item) => item.job_type === "verify");
    if (verifyJob?.job_id) {
      await clickIfEnabled(page.getByTestId(`retry-verify-job-${verifyJob.job_id}`));
      await page.waitForTimeout(1200);
    }
    await shot("index-console-complete");
    return { jobCount: jobs.data.items.length, sampledVerifyJob: verifyJob?.job_id || null };
  });

  const interop = await step("interop preview/import/export/replay final row", async () => {
    const suffix = `${Date.now()}`.slice(-6);
    const bundleId = `bundle_interop_three_chapter_qa_${suffix}`;
    await page.getByTestId("nav-interop").click();
    await page.getByTestId("interop-center-view").waitFor({ timeout: 30000 });
    const worksheet = `
bundle_id: ${bundleId}
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
    await page.getByTestId("interop-export-bundle-id").fill(bundleId);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/interop/export/bundle-worksheet/${bundleId}`), { timeout: 30000 }),
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
    await shot("interop-center-complete");
    return { bundleId, replayFinalRowId: "final_scene_CHQA01_SC01_v5" };
  });

  const trash = await step("author trash scene restore and chapter purge", async () => {
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
    await shot("author-trash-complete");
    return { chapterId, restoredSceneId: sceneB, purgedChapterId: chapterId };
  });

  const chapters = {};
  for (const chapterId of ["CHQA01", "CHQA02", "CHQA03"]) {
    const status = (await get(`/api/v1/chapters/${chapterId}/status`)).data;
    chapters[chapterId] = {
      finalMemory: status.chapter_runtime?.last_final_memory_row_id || null,
      aggregateBlockReason: status.chapter_runtime?.aggregate_block_reason || null,
      passedSceneCount: status.chapter_runtime?.chapter_passed_scene_count || 0,
      manualHoldReason: status.chapter_runtime?.manual_hold_reason || null,
    };
  }
  result.reference = reference;
  result.config = config;
  result.review = review;
  result.index = index;
  result.interop = interop;
  result.trash = trash;
  result.chapters = chapters;
  await shot("remaining-pages-final");
  return result;
}
