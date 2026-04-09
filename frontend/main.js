import "./app.css";

const state = {
  apiBase: localStorage.getItem("novel-system-api-base") || "http://127.0.0.1:8000",
  activeView: "workbench",
  workbenchSceneId: "CH001_SC01",
  reviews: [],
  workbench: null,
  aliasScopes: [],
  jobs: [],
  humanReview: [],
  notices: [],
};
let eventsBound = false;

function boot() {
  render();
  bindEvents();
  loadAll();
}

function render() {
  const app = document.querySelector("#app");
  app.innerHTML = `
    <div class="shell">
      <aside class="rail">
        <div class="brand">
          <div class="eyebrow">P2 Editorial Ops</div>
          <h1>Novel System Console</h1>
          <p>把场景、审校和向量索引放在同一张工作台上。</p>
        </div>
        <label class="api-label">
          API Base
          <input id="apiBaseInput" value="${state.apiBase}" />
        </label>
        <nav class="nav">
          ${navButton("workbench", "Scene Workbench")}
          ${navButton("review", "Review Inbox")}
          ${navButton("index", "Index Console")}
        </nav>
        <button class="ghost" id="reloadAll">刷新全部</button>
        <div class="notice-stack">
          ${state.notices.map((notice) => `<div class="notice">${notice}</div>`).join("")}
        </div>
      </aside>
      <main class="stage">
        ${renderWorkbench()}
        ${renderReviewInbox()}
        ${renderIndexConsole()}
      </main>
    </div>
  `;
}

function navButton(view, label) {
  return `<button class="nav-btn ${state.activeView === view ? "active" : ""}" data-view="${view}">${label}</button>`;
}

function renderWorkbench() {
  const hidden = state.activeView === "workbench" ? "" : "hidden";
  const data = state.workbench;
  return `
    <section class="panel-grid" ${hidden}>
      <section class="hero-panel panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Scene Workbench</div>
            <h2>场景闭环与回放</h2>
          </div>
          <div class="actions">
            <input id="sceneIdInput" value="${state.workbenchSceneId}" />
            <button id="loadWorkbench">读取</button>
          </div>
        </div>
        ${
          data
            ? `
          <div class="stats">
            <div class="stat">
              <span>Bundle</span>
              <strong>${data.bundle?.bundle_id || "-"}</strong>
            </div>
            <div class="stat">
              <span>Hash</span>
              <strong>${data.bundle?.bundle_snapshot_hash || "-"}</strong>
            </div>
            <div class="stat">
              <span>Status</span>
              <strong>${data.scene_run_state.scene_status}</strong>
            </div>
          </div>
          <div class="workbench-columns">
            <article class="paper">
              <h3>Chapter / Scene</h3>
              <p><strong>${data.chapter_goal.chapter_goal}</strong></p>
              <p>${data.scene_card.scene_goal}</p>
              <p class="muted">地点：${data.scene_card.location || "-"}</p>
              <p class="muted">Must include：${data.scene_card.must_include_text || "-"}</p>
            </article>
            <article class="paper">
              <h3>Draft Lineage</h3>
              <p><strong>Neutral</strong><br />${data.neutral_draft?.content || "-"}</p>
              <p><strong>Style</strong><br />${data.style_draft?.content || "-"}</p>
              <p><strong>Final</strong><br />${data.final_scene?.content || "-"}</p>
            </article>
            <article class="paper">
              <h3>Archive / Gate</h3>
              <p><strong>Scene Memory</strong><br />${data.scene_memory?.content || "-"}</p>
              <p class="muted">Backfill pending：${data.chapter_state.chapter_backfill_pending_count}</p>
              <p class="muted">Aggregate gate：${data.chapter_state.aggregate_block_reason}</p>
            </article>
          </div>
        `
            : `<div class="empty">输入场景 ID 后读取 workbench。</div>`
        }
      </section>
      <section class="panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Attempt Timeline</div>
            <h2>执行轨迹</h2>
          </div>
        </div>
        <div class="timeline">
          ${(data?.attempts || []).map(renderAttempt).join("") || '<div class="empty">还没有 attempt 记录。</div>'}
        </div>
      </section>
      <section class="panel drawer">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Human Review Drawer</div>
            <h2>人工回流</h2>
          </div>
        </div>
        <div class="drawer-body">
          ${(state.humanReview || []).slice(0, 3).map(renderHumanReview).join("") || '<div class="empty">当前没有人工 review 事件。</div>'}
        </div>
      </section>
    </section>
  `;
}

function renderAttempt(item) {
  return `
    <div class="attempt">
      <div class="attempt-step">${item.step}</div>
      <div class="attempt-body">
        <div>${item.status}</div>
        <div class="muted">${item.source_bundle_id || "pre-bundle"}</div>
      </div>
    </div>
  `;
}

function renderHumanReview(item) {
  return `
    <article class="paper mini">
      <h3>${item.event_source}</h3>
      <p class="muted">状态：${item.status}</p>
      <p class="muted">允许动作：${(item.allowed_actions_json || []).join(" / ") || "无"}</p>
    </article>
  `;
}

function renderReviewInbox() {
  const hidden = state.activeView === "review" ? "" : "hidden";
  return `
    <section class="panel-grid" ${hidden}>
      <section class="panel hero-panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Review Inbox</div>
            <h2>审批、物化与 release</h2>
          </div>
          <div class="actions">
            <button id="refreshReviews">刷新列表</button>
          </div>
        </div>
        <div class="review-list">
          ${
            state.reviews.length
              ? state.reviews.map(renderReviewCard).join("")
              : '<div class="empty">当前没有 review item。</div>'
          }
        </div>
      </section>
    </section>
  `;
}

function renderReviewCard(item) {
  return `
    <article class="review-card">
      <div class="review-meta">
        <span class="badge">${item.target_collection}</span>
        <span class="muted">${item.review_id}</span>
      </div>
      <h3>${item.candidate_text || "空文本 candidate"}</h3>
      <pre>${JSON.stringify(item.candidate_payload_json, null, 2)}</pre>
      <div class="card-actions">
        <button data-approve="${item.review_id}">Approve</button>
        <button data-release="${item.review_id}" ${item.materialize_status !== "succeeded" ? "disabled" : ""}>Release</button>
      </div>
    </article>
  `;
}

function renderIndexConsole() {
  const hidden = state.activeView === "index" ? "" : "hidden";
  return `
    <section class="panel-grid" ${hidden}>
      <section class="panel hero-panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Index Console</div>
            <h2>Alias、Verify 与 Recovery</h2>
          </div>
          <div class="actions">
            <button id="refreshIndex">刷新索引</button>
            <button id="runRecovery">Recovery Sweep</button>
          </div>
        </div>
        <div class="alias-grid">
          ${
            state.aliasScopes.length
              ? state.aliasScopes.map(renderAliasCard).join("")
              : '<div class="empty">当前没有 alias scope。</div>'
          }
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">
          <div>
            <div class="eyebrow">Jobs</div>
            <h2>Reindex / Verify</h2>
          </div>
        </div>
        <div class="job-table">
          ${
            state.jobs.length
              ? state.jobs.map(renderJob).join("")
              : '<div class="empty">当前没有索引任务。</div>'
          }
        </div>
      </section>
    </section>
  `;
}

function renderAliasCard(item) {
  return `
    <article class="paper">
      <h3>${item.alias_scope}</h3>
      <p><strong>Active</strong> ${item.active_alias || "-"}</p>
      <p><strong>Candidate</strong> ${item.candidate_alias || "-"}</p>
      <p class="muted">verify：${item.verify_status}</p>
      <p class="muted">embedding：${item.active_embedding_version || "-"} / ${item.candidate_embedding_version || "-"}</p>
    </article>
  `;
}

function renderJob(item) {
  return `
    <div class="job-row">
      <div>
        <strong>${item.job_type}</strong>
        <div class="muted">${item.job_id}</div>
      </div>
      <div class="muted">${item.status}</div>
      <div class="muted">${item.alias_scope}</div>
      <div class="job-actions">
        ${
          item.job_type === "verify"
            ? `<button data-verify="${item.job_id}">Retry Verify</button>`
            : `<span class="muted">auto built</span>`
        }
      </div>
    </div>
  `;
}

function bindEvents() {
  if (eventsBound) return;
  eventsBound = true;
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (target.dataset.view) {
      state.activeView = target.dataset.view;
      render();
      bindEvents();
      return;
    }
    if (target.id === "reloadAll") {
      await loadAll();
      return;
    }
    if (target.id === "loadWorkbench") {
      state.workbenchSceneId = document.querySelector("#sceneIdInput").value.trim();
      await loadWorkbench();
      return;
    }
    if (target.id === "refreshReviews") {
      await loadReviews();
      return;
    }
    if (target.id === "refreshIndex") {
      await loadIndex();
      return;
    }
    if (target.id === "runRecovery") {
      await postAction("/api/v1/runtime/recovery/sweep");
      await loadIndex();
      return;
    }
    if (target.dataset.approve) {
      await postAction(`/api/v1/review-items/${target.dataset.approve}/approve`);
      await Promise.all([loadReviews(), loadIndex()]);
      return;
    }
    if (target.dataset.release) {
      await postAction(`/api/v1/review-items/${target.dataset.release}/release`);
      await Promise.all([loadReviews(), loadIndex()]);
      return;
    }
    if (target.dataset.verify) {
      await postAction(`/api/v1/index/verify/${target.dataset.verify}/retry`);
      await loadIndex();
    }
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.id === "apiBaseInput") {
      state.apiBase = target.value.trim();
      localStorage.setItem("novel-system-api-base", state.apiBase);
    }
  });
}

async function loadAll() {
  await Promise.all([loadWorkbench(), loadReviews(), loadIndex(), loadHumanReview()]);
}

async function loadWorkbench() {
  try {
    state.workbench = await fetchJSON(`/api/v1/scenes/${state.workbenchSceneId}/workbench`);
  } catch (error) {
    pushNotice(error.message);
  }
  render();
  bindEvents();
}

async function loadReviews() {
  try {
    const payload = await fetchJSON("/api/v1/review-items");
    state.reviews = payload.items || [];
  } catch (error) {
    pushNotice(error.message);
  }
  render();
  bindEvents();
}

async function loadIndex() {
  try {
    const [aliasScopes, jobs] = await Promise.all([
      fetchJSON("/api/v1/index/alias-scopes"),
      fetchJSON("/api/v1/index/jobs")
    ]);
    state.aliasScopes = aliasScopes.items || [];
    state.jobs = jobs.items || [];
  } catch (error) {
    pushNotice(error.message);
  }
  render();
  bindEvents();
}

async function loadHumanReview() {
  try {
    const payload = await fetchJSON("/api/v1/human-review-events");
    state.humanReview = payload.items || [];
  } catch (error) {
    pushNotice(error.message);
  }
  render();
  bindEvents();
}

async function postAction(path) {
  try {
    const response = await fetch(`${state.apiBase}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": `${path}-${Date.now()}`
      }
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error?.message || `Request failed: ${response.status}`);
    }
    pushNotice(`已执行：${path}`);
  } catch (error) {
    pushNotice(error.message);
  }
}

async function fetchJSON(path) {
  const response = await fetch(`${state.apiBase}${path}`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `Request failed: ${response.status}`);
  }
  return payload.data;
}

function pushNotice(message) {
  if (!message) return;
  state.notices = [message, ...state.notices].slice(0, 4);
}

boot();
