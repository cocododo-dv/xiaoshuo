// ws-scene-run store 层单测：队列成员的后端派生（scnBackendQueueSids）。
// 贯通轮遗留 ①：GET /scene-run-states 是队列成员真相源，localStorage 退化为读缓存——
// 这里验证「run-states → 目录 backendId 对位 → sid 列表」的派生契约与其兜底路径。
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { readFileSync } from "node:fs";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_CHAP, DEFAULT_PROJECT } from "./test-helpers.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  cancelRunJob: vi.fn(),
  getLatestSceneRunJob: vi.fn(),
}));

// ws-scene-run 只从 ws-snow.jsx 取 s2ExportState（提示词上下文，与本测试无关）；
// ws-catalog 链上的 ws-snow-sync 只取 S2_BE_STEPS。mock 掉避免拉入整张雪花视图。
vi.mock("./ws-snow.jsx", () => ({ S2_BE_STEPS: [], s2ExportState: () => null }));

const T = { timeout: 5000, interval: 25 };

const RUN_STATES_URL = /^\/api\/v1\/scene-run-states\?/;
const NON_DEMO_PROJECT = { ...DEFAULT_PROJECT, project_id: "novel-1", title: "回归小说", is_demo: false };
const TWO_SCENE_CHAP = {
  ...DEFAULT_CHAP,
  scenes: [
    ...DEFAULT_CHAP.scenes,
    {
      ...DEFAULT_CHAP.scenes[0],
      slug: "ch01s2",
      scene_id: "s2",
      title: "回潮",
      brief: { goal: "追上证人", conflict: "潮水封路", setback: "证人失踪" },
    },
  ],
};

async function settleActive(projectId = "tide") {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe(projectId), T);
}

/* 在 installApiRouter 之上叠一层 scene-run-states 路由（贯通轮惯用法：包装现有实现） */
function routeRunStates(client, responder) {
  const base = client.apiGet.getMockImplementation();
  client.apiGet.mockImplementation((url) => {
    if (RUN_STATES_URL.test(url)) return responder(url);
    return base(url);
  });
}

async function loadSceneRun(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  const mod = await import("./ws-scene-run.jsx");
  await settleActive((opts && opts.projects && opts.projects[0] && opts.projects[0].project_id) || "tide");
  return { mod, client };
}

const mountedRoots = [];

async function renderRunJobControl(Component, props) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mountedRoots.push({ root, host });
  await act(async () => {
    root.render(<Component {...props} />);
  });
  return {
    host,
    rerender: async (nextProps) => {
      await act(async () => {
        root.render(<Component {...nextProps} />);
      });
    },
    unmount: async () => {
      const index = mountedRoots.findIndex((item) => item.root === root);
      if (index >= 0) mountedRoots.splice(index, 1);
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("scene run cancellation client", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the authoritative latest path and the shared POST idempotency contract", async () => {
    const client = await vi.importActual("./lib/client.js");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, data: { job_id: "job/latest" } }),
      })
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, data: { job_id: "job/retry", status: "cancel_requested" } }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await client.getLatestSceneRunJob("SC /一");
    await expect(client.cancelRunJob("job/retry")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      retryable: true,
    });
    await client.cancelRunJob("job/retry");

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/scenes\/SC%20%2F%E4%B8%80\/run\/jobs\/latest$/);
    const firstCancel = fetchMock.mock.calls[1];
    const retryCancel = fetchMock.mock.calls[2];
    expect(firstCancel[0]).toMatch(/\/api\/v1\/run-jobs\/job%2Fretry\/cancel$/);
    expect(firstCancel[1]).toMatchObject({ method: "POST", body: "{}" });
    expect(firstCancel[1].headers["X-Operator-Ref"]).toBe("operator");
    expect(firstCancel[1].headers["X-Idempotency-Key"]).toBeTruthy();
    expect(retryCancel[1].headers["X-Idempotency-Key"]).toBe(
      firstCancel[1].headers["X-Idempotency-Key"],
    );
  });

  it("forwards AbortSignal to fetch and reports an intentional abort faithfully", async () => {
    const client = await vi.importActual("./lib/client.js");
    let fetchSignal = null;
    vi.stubGlobal("fetch", vi.fn((url, init) => new Promise((resolve, reject) => {
      void url;
      void resolve;
      fetchSignal = init.signal;
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    })));
    const controller = new AbortController();

    const pending = client.getLatestSceneRunJob("SC01", { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ code: "REQUEST_ABORTED", retryable: true });
    expect(fetchSignal).toBe(controller.signal);
    expect(fetchSignal.aborted).toBe(true);
  });
});

describe("SceneRunJobControl", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });

  afterEach(async () => {
    while (mountedRoots.length) {
      const { root, host } = mountedRoots.pop();
      await act(async () => root.unmount());
      host.remove();
    }
    vi.restoreAllMocks();
  });

  it("treats latest 404 as an ordinary no-job state with accessible status", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockRejectedValue(
      Object.assign(new Error("not found"), { status: 404, code: "RUN_JOB_NOT_FOUND" }),
    );

    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });

    await vi.waitFor(() => {
      expect(view.host.querySelector('[role="status"]')?.textContent).toContain("暂无运行任务");
    }, T);
    expect(view.host.querySelector('[role="alert"]')).toBeNull();
    expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeNull();
  });

  it.each(["queued", "running"])("cancels %s once despite repeated clicks", async (status) => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockResolvedValue({ job_id: `job-${status}`, scene_id: "SC01", status });
    let resolveCancel;
    client.cancelRunJob.mockImplementation(() => new Promise((resolve) => { resolveCancel = resolve; }));

    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy(), T);
    const button = view.host.querySelector('[data-testid="scene-run-cancel-button"]');
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(button.disabled).toBe(true);
    expect(client.cancelRunJob).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCancel({ job_id: `job-${status}`, scene_id: "SC01", status: "cancel_requested" });
    });
    expect(view.host.querySelector('[role="status"]').textContent).toContain("正在取消");
    expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')?.disabled).toBe(true);
  });

  it("polls cancel_requested until cancelled and exposes every state through aria-live", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob
      .mockResolvedValueOnce({ job_id: "job-1", scene_id: "SC01", status: "cancel_requested" })
      .mockResolvedValue({ job_id: "job-1", scene_id: "SC01", status: "cancelled" });

    const view = await renderRunJobControl(mod.SceneRunJobControl, {
      sceneId: "SC01",
      pollIntervalMs: 5,
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 15));
    });

    await vi.waitFor(() => {
      const status = view.host.querySelector('[role="status"]');
      expect(status?.getAttribute("aria-live")).toBe("polite");
      expect(status?.textContent).toContain("已取消");
    }, T);
    expect(client.getLatestSceneRunJob.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeNull();
  });

  it("keeps a committed POST job newer than an older latest request", async () => {
    const { mod, client } = await loadSceneRun();
    let rejectOldLatest;
    client.getLatestSceneRunJob.mockImplementation(() => new Promise((resolve, reject) => {
      rejectOldLatest = reject;
    }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });

    await view.rerender({
      sceneId: "SC01",
      observedJob: { job_id: "job-new", scene_id: "SC01", status: "running" },
    });
    await vi.waitFor(() => expect(view.host.querySelector('[role="status"]')?.textContent).toContain("运行中"), T);
    await act(async () => {
      rejectOldLatest(Object.assign(new Error("not found"), { status: 404, code: "RUN_JOB_NOT_FOUND" }));
    });

    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-new");
  });

  it("does not regress cancel_requested when an older running observation arrives late", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockResolvedValue({ job_id: "job-monotonic", scene_id: "SC01", status: "running" });
    client.cancelRunJob.mockResolvedValue({ job_id: "job-monotonic", scene_id: "SC01", status: "cancel_requested" });
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy(), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));
    await vi.waitFor(() => expect(view.host.querySelector('[role="status"]')?.textContent).toContain("正在取消"), T);
    await view.rerender({
      sceneId: "SC01",
      observedJob: { job_id: "job-monotonic", scene_id: "SC01", status: "running" },
    });

    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe("cancel_requested");
    expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')?.disabled).toBe(true);
  });

  it("does not let a late cancel response for job A overwrite a newer latest job B", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob
      .mockResolvedValueOnce({ job_id: "job-a", scene_id: "SC01", status: "running" })
      .mockResolvedValue({ job_id: "job-b", scene_id: "SC01", status: "completed" });
    let resolveCancelA;
    client.cancelRunJob.mockImplementation(() => new Promise(resolve => { resolveCancelA = resolve; }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, {
      sceneId: "SC01",
      pollIntervalMs: 5,
    });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-a"), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); });
    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-b");
    await act(async () => {
      resolveCancelA({ job_id: "job-a", scene_id: "SC01", status: "cancelled" });
    });

    await vi.waitFor(() => {
      const control = view.host.querySelector('[data-testid="scene-run-job-control"]');
      expect(control?.dataset.jobId).toBe("job-b");
      expect(control?.dataset.status).toBe("completed");
      expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeNull();
    }, T);
  });

  it("does not attach a late cancel failure for job A to a newer latest job B", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob
      .mockResolvedValueOnce({ job_id: "job-a", scene_id: "SC01", status: "running" })
      .mockResolvedValue({ job_id: "job-b", scene_id: "SC01", status: "completed" });
    let rejectCancelA;
    client.cancelRunJob.mockImplementation(() => new Promise((resolve, reject) => {
      void resolve;
      rejectCancelA = reject;
    }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, {
      sceneId: "SC01",
      pollIntervalMs: 5,
    });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-a"), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); });
    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-b");
    await act(async () => {
      rejectCancelA(Object.assign(new Error("cancel A failed"), { code: "NETWORK_ERROR", retryable: true }));
    });

    await vi.waitFor(() => {
      const control = view.host.querySelector('[data-testid="scene-run-job-control"]');
      expect(control?.dataset.jobId).toBe("job-b");
      expect(control?.dataset.status).toBe("completed");
      expect(view.host.querySelector('[role="alert"]')).toBeNull();
    }, T);
  });

  it("refreshSignal refetches a terminal job so the banner converges to archived", async () => {
    // C2 状态一致性债务：归档后终态 job 不轮询，横幅停在旧暂停点
    // （awaiting_candidate_selection）；父组件归档成功后递增 refreshSignal
    // 强制重取 latest，后端视图层已把 current_step 收敛为 archived。
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob
      .mockResolvedValueOnce({
        job_id: "job-adopt",
        scene_id: "SC01",
        status: "completed",
        current_step: "awaiting_candidate_selection",
      })
      .mockResolvedValue({
        job_id: "job-adopt",
        scene_id: "SC01",
        status: "completed",
        current_step: "archived",
        scene_status: "archived",
      });

    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => {
      expect(view.host.querySelector('[role="status"]')?.textContent).toContain("awaiting_candidate_selection");
    }, T);
    // 终态 job 不轮询：没有 refreshSignal 时不会自己刷新
    expect(client.getLatestSceneRunJob).toHaveBeenCalledTimes(1);

    await view.rerender({ sceneId: "SC01", refreshSignal: 1 });

    await vi.waitFor(() => {
      expect(view.host.querySelector('[role="status"]')?.textContent).toContain("archived");
    }, T);
    expect(client.getLatestSceneRunJob).toHaveBeenCalledTimes(2);
    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe("completed");
  });

  it("still shows a cancel network failure when an intervening latest poll remains on job A", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: "job-a",
      scene_id: "SC01",
      status: "running",
    });
    let rejectCancelA;
    client.cancelRunJob.mockImplementation(() => new Promise((resolve, reject) => {
      void resolve;
      rejectCancelA = reject;
    }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, {
      sceneId: "SC01",
      pollIntervalMs: 20,
    });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-a"), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
    expect(client.getLatestSceneRunJob.mock.calls.length).toBeGreaterThanOrEqual(2);
    await act(async () => {
      rejectCancelA(Object.assign(new Error("cancel A failed"), { code: "NETWORK_ERROR", retryable: true }));
    });

    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-a");
    expect(view.host.querySelector('[role="alert"]')?.textContent).toContain("cancel A failed");
    expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')?.disabled).toBe(false);
    await view.unmount();
  });

  it("publishes only the POST-created job and never feeds job-specific poll results into observedJob", async () => {
    const { mod, client } = await loadSceneRun();
    const baseGet = client.apiGet.getMockImplementation();
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/run\/jobs$/.test(url)) {
        return Promise.resolve({ job_id: "job-created", scene_id: "s1", status: "running" });
      }
      return Promise.resolve({});
    });
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v1/run-jobs/job-created") {
        return Promise.resolve({ job_id: "job-created", scene_id: "s1", status: "completed" });
      }
      if (url === "/api/v1/scenes/s1/workbench") {
        return Promise.resolve({
          neutral_draft: { content: "潮水退去。\n她留下了证词。" },
          scene_run_state: { scene_status: "ready" },
        });
      }
      return baseGet(url);
    });
    const onJobCreated = vi.fn();
    vi.useFakeTimers();
    try {
      const runPromise = mod.scnRun(
        { sid: "ch01s1", kind: "主动场景" },
        "",
        "",
        { onJobCreated },
      );
      await vi.runAllTimersAsync();
      await runPromise;
    } finally {
      vi.useRealTimers();
    }

    expect(onJobCreated).toHaveBeenCalledTimes(1);
    expect(onJobCreated).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: "job-created", status: "running" }),
      "s1",
    );
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/s1/run/jobs",
      { run_policy: "strict" },
    );
  });

  it("keeps a neutral draft non-archivable when the durable job is blocked by lifecycle budget", async () => {
    const { mod, client } = await loadSceneRun();
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/run\/jobs$/.test(url)) {
        return Promise.resolve({ job_id: "job-budget", scene_id: "s1", status: "running" });
      }
      return Promise.resolve({});
    });
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v1/run-jobs/job-budget") {
        return Promise.resolve({
          job_id: "job-budget",
          scene_id: "s1",
          status: "blocked",
          current_step: "blocked",
          error_code: "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
          error_text: "scene token budget exhausted before dispatch",
        });
      }
      if (url === "/api/v1/scenes/s1/workbench") {
        return Promise.resolve({
          neutral_draft: { content: "潮水退去。\n她留下了证词。" },
          scene_run_state: {
            scene_status: "bundle_built",
            lifecycle_budget: {
              scene_token_budget: 34200,
              scene_tokens_used: 13615,
              scene_tokens_reserved: 0,
              scene_tokens_remaining: 20585,
              baseline_tokens: 6840,
              recommended_topup_tokens: 6840,
              attempt_budget: 4,
              total_attempt_count: 2,
              provider_attempt_budget: 32,
              provider_attempts_used: 5,
            },
          },
          author_state: { author_state: "draft_ready", can_archive: true },
        });
      }
      return baseGet(url);
    });

    vi.useFakeTimers();
    let result;
    try {
      const pending = mod.scnRun({ sid: "ch01s1", kind: "主动场景" }, "", "");
      await vi.runAllTimersAsync();
      result = await pending;
    } finally {
      vi.useRealTimers();
    }

    expect(result.budgetBlock).toMatchObject({
      code: "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
      topup: { extra_tokens: 6840 },
    });
    expect(result.gate.canArchive).toBe(false);
    expect(result.draft.length).toBeGreaterThan(0);
  });

  it("topups only the exhausted lifecycle dimension through the audited author route", async () => {
    const { mod, client } = await loadSceneRun();
    client.apiPost.mockResolvedValue({ scene_token_budget: 41040 });

    await mod.scnTopupBudget("ch01s1", {
      code: "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
      topup: { extra_tokens: 6840 },
    });

    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/s1/budget/topup",
      {
        extra_tokens: 6840,
        reason: "作者在起草台确认追加生命周期预算并从持久化检查点继续",
      },
    );
  });

  it("asks the server to resume its own budget-blocked checkpoint instead of starting a fresh execution", async () => {
    const { mod, client } = await loadSceneRun();
    client.apiPost.mockImplementation((url) => {
      if (url === "/api/v1/scenes/s1/run/jobs") {
        return Promise.resolve({ job_id: "job-resume-budget", scene_id: "s1", status: "completed" });
      }
      return Promise.resolve({});
    });
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v1/scenes/s1/workbench") {
        return Promise.resolve({
          style_draft: { content: "潮水退去。\n她留下了证词。" },
          scene_run_state: { scene_status: "near_final" },
        });
      }
      return baseGet(url);
    });

    await mod.scnRun(
      { sid: "ch01s1", kind: "主动场景" },
      "",
      "",
      { resumeBudget: true },
    );

    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/s1/run/jobs",
      { run_policy: "strict", resume_budget: true },
    );
  });

  it("projects a server-archived completed run as archived instead of a blocked ready state", async () => {
    const { mod, client } = await loadSceneRun();
    client.apiPost.mockImplementation((url) => {
      if (url === "/api/v1/scenes/s1/run/jobs") {
        return Promise.resolve({ job_id: "job-archived", scene_id: "s1", status: "completed" });
      }
      return Promise.resolve({});
    });
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v1/scenes/s1/workbench") {
        return Promise.resolve({
          final_scene: { content: "潮水退去。\n她留下了证词。" },
          scene_run_state: { scene_status: "archived" },
          author_state: { author_state: "archived", can_archive: false },
        });
      }
      return baseGet(url);
    });

    const result = await mod.scnRun({ sid: "ch01s1", kind: "主动场景" }, "", "");

    expect(result.state).toBe("archived");
    expect(result.gate).toMatchObject({ authorState: "archived", canArchive: false });
  });

  it("aborts an in-flight job-specific GET instead of merely ignoring its response", async () => {
    const { mod, client } = await loadSceneRun();
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/run\/jobs$/.test(url)) {
        return Promise.resolve({ job_id: "job-pending-get", scene_id: "s1", status: "running" });
      }
      return Promise.resolve({});
    });
    let getSignal = null;
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url, { signal } = {}) => {
      if (url !== "/api/v1/run-jobs/job-pending-get") return baseGet(url);
      getSignal = signal;
      return new Promise((resolve, reject) => {
        void resolve;
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    });
    const controller = new AbortController();
    vi.useFakeTimers();
    try {
      const pending = mod.scnRun(
        { sid: "ch01s1", kind: "主动场景" },
        "",
        "",
        { signal: controller.signal },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await vi.waitFor(() => expect(getSignal).toBe(controller.signal), T);
      controller.abort();
      await expect(pending).rejects.toMatchObject({ code: "SCENE_RUN_UI_ABORTED" });
      expect(getSignal.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["cancelled", "completed", "failed", "blocked"])(
    "renders terminal %s without an executable cancel action",
    async (status) => {
      const { mod, client } = await loadSceneRun();
      client.getLatestSceneRunJob.mockResolvedValue({ job_id: `job-${status}`, scene_id: "SC01", status });
      const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });

      await vi.waitFor(() => {
        expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe(status);
      }, T);
      expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeNull();
    },
  );

  it("shows backend 409 reason/details and refreshes the authoritative terminal state", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob
      .mockResolvedValueOnce({ job_id: "job-race", scene_id: "SC01", status: "running" })
      .mockResolvedValue({ job_id: "job-race", scene_id: "SC01", status: "completed" });
    client.cancelRunJob.mockRejectedValue(Object.assign(new Error("terminal scene run job cannot be cancelled"), {
      status: 409,
      code: "RUN_JOB_CANCEL_CONFLICT",
      details: { job_id: "job-race", status: "completed" },
    }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy(), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));

    await vi.waitFor(() => {
      const alert = view.host.querySelector('[role="alert"]');
      expect(alert?.textContent).toContain("RUN_JOB_CANCEL_CONFLICT");
      expect(alert?.textContent).toContain("completed");
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe("completed");
    }, T);
  });

  it("re-enables retry after a network failure without issuing a duplicate in-flight cancel", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockResolvedValue({ job_id: "job-network", scene_id: "SC01", status: "running" });
    client.cancelRunJob
      .mockRejectedValueOnce(Object.assign(new Error("network down"), { code: "NETWORK_ERROR", retryable: true }))
      .mockResolvedValueOnce({ job_id: "job-network", scene_id: "SC01", status: "cancel_requested" });
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy(), T);

    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));
    await vi.waitFor(() => {
      expect(view.host.querySelector('[role="alert"]')?.textContent).toContain("network down");
      expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')?.disabled).toBe(false);
    }, T);
    await click(view.host.querySelector('[data-testid="scene-run-cancel-button"]'));

    expect(client.cancelRunJob).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(view.host.querySelector('[role="status"]')?.textContent).toContain("正在取消"), T);
  });

  it("does not let a stale scene response overwrite the newly selected scene", async () => {
    const { mod, client } = await loadSceneRun();
    let resolveA;
    client.getLatestSceneRunJob.mockImplementation((sceneId) => {
      if (sceneId === "SC-A") return new Promise((resolve) => { resolveA = resolve; });
      return Promise.resolve({ job_id: "job-b", scene_id: "SC-B", status: "cancelled" });
    });
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC-A" });

    await view.rerender({ sceneId: "SC-B" });
    await vi.waitFor(() => expect(view.host.querySelector('[role="status"]')?.textContent).toContain("已取消"), T);
    await act(async () => resolveA({ job_id: "job-a", scene_id: "SC-A", status: "running" }));

    expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-b");
    expect(view.host.querySelector('[role="status"]')?.textContent).toContain("已取消");
  });

  it("cleans its polling timer on unmount and reloads latest after a fresh mount", async () => {
    const { mod, client } = await loadSceneRun();
    client.getLatestSceneRunJob.mockResolvedValue({ job_id: "job-live", scene_id: "SC01", status: "cancel_requested" });
    const first = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01", pollIntervalMs: 80 });
    await vi.waitFor(() => expect(client.getLatestSceneRunJob).toHaveBeenCalledTimes(1), T);
    await first.unmount();
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(client.getLatestSceneRunJob).toHaveBeenCalledTimes(1);

    await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01", pollIntervalMs: 80 });
    await vi.waitFor(() => expect(client.getLatestSceneRunJob).toHaveBeenCalledTimes(2), T);
  });

  it("aborts an in-flight latest request when the control unmounts", async () => {
    const { mod, client } = await loadSceneRun();
    let latestSignal = null;
    client.getLatestSceneRunJob.mockImplementation((sceneId, { signal }) => new Promise((resolve, reject) => {
      void sceneId;
      void resolve;
      latestSignal = signal;
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    const view = await renderRunJobControl(mod.SceneRunJobControl, { sceneId: "SC01" });
    await vi.waitFor(() => expect(latestSignal).toBeTruthy(), T);

    await view.unmount();

    expect(latestSignal.aborted).toBe(true);
  });

  it("is mounted by the real scene page instead of shipping as a dead component", () => {
    const source = readFileSync("src/ws-scene.jsx", "utf8");
    expect(source).toContain("SceneRunJobControl");
    expect(source).toContain("authoritativeRunJob");
    expect(source).toContain("onJobChange");
  });

  it("restores latest running state and cancel control in the real scene page", async () => {
    const { client } = await loadSceneRun();
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: "job-page-refresh",
      scene_id: "s1",
      status: "running",
      current_step: "neutral_running",
    });
    const page = await import("./ws-scene.jsx");

    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });

    await vi.waitFor(() => {
      expect(client.getLatestSceneRunJob).toHaveBeenCalledWith(
        "s1",
        expect.objectContaining({ signal: expect.anything() }),
      );
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-page-refresh");
      expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy();
      expect(view.host.querySelector('[role="status"]')?.textContent).toContain("neutral_running");
    }, T);
  });

  it("keeps authoritative queued distinct from running and suppresses a duplicate start", async () => {
    const { client } = await loadSceneRun();
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: "job-page-queued",
      scene_id: "s1",
      status: "queued",
      current_step: "queued",
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });

    await vi.waitFor(() => {
      expect(view.host.querySelector(".scn2-state-tag")?.textContent).toContain("排队");
      expect(view.host.querySelector('[role="status"]')?.textContent).toContain("排队中");
      expect(view.host.querySelector('[data-testid="scene-run-cancel-button"]')).toBeTruthy();
    }, T);
    const executableStart = Array.from(view.host.querySelectorAll("button"))
      .find((button) => button.textContent.includes("开始起草") && !button.disabled);
    expect(executableStart).toBeUndefined();
  });

  it("selects the first backend-restored scene from an empty local queue and aligns stage, row, and counts", async () => {
    const { client } = await loadSceneRun({ projects: [NON_DEMO_PROJECT] });
    routeRunStates(client, () => Promise.resolve({
      items: [{ scene_id: "s1", scene_status: "neutral_running" }],
    }));
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: "job-empty-restore",
      scene_id: "s1",
      status: "running",
      current_step: "neutral_running",
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });

    await vi.waitFor(() => {
      expect(view.host.textContent).not.toContain("运行队列还是空的");
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.jobId).toBe("job-empty-restore");
      expect(view.host.querySelector(".scn2-state-tag")?.textContent).toContain("运行");
      expect(view.host.querySelector(".scn2-qrow.is-active .scn2-chip")?.textContent).toContain("运行");
    }, T);
    const stats = Array.from(view.host.querySelectorAll(".scn2-stat"));
    const running = stats.find(item => item.querySelector(".scn2-stat-label")?.textContent === "运行");
    const queued = stats.find(item => item.querySelector(".scn2-stat-label")?.textContent === "排队");
    expect(running?.querySelector(".scn2-stat-num")?.textContent).toBe("1");
    expect(queued?.querySelector(".scn2-stat-num")?.textContent).toBe("0");
  });

  it.each([
    { terminal: "completed", expectedRow: "待复核", expectReview: true },
    { terminal: "cancelled", expectedRow: "排队", expectReview: false },
  ])("reconciles stale local running after A → B → A when latest is $terminal", async ({ terminal, expectedRow, expectReview }) => {
    const { mod, client } = await loadSceneRun({
      projects: [NON_DEMO_PROJECT],
      catalog: [TWO_SCENE_CHAP],
    });
    mod.scnRunSave("ch01s1", {
      state: "running",
      progress: 0.4,
      attempt: 1,
      draft: [],
      metrics: [],
      alignment: [],
      cost: [],
      log: [],
    });
    window.__scnEnqueue = { sids: ["ch01s1", "ch01s2"] };
    const notFound = Object.assign(new Error("not found"), { status: 404, code: "RUN_JOB_NOT_FOUND" });
    let aReads = 0;
    client.getLatestSceneRunJob.mockImplementation((sceneId) => {
      if (sceneId === "s2") return Promise.reject(notFound);
      aReads += 1;
      return Promise.resolve({
        job_id: "job-scene-a",
        scene_id: "s1",
        status: aReads === 1 ? "running" : terminal,
      });
    });
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url, options) => {
      if (url === "/api/v1/scenes/s1/workbench") {
        return Promise.resolve({
          neutral_draft: { content: "潮水退去。\n她留下了证词。" },
          scene_run_state: { scene_status: "ready" },
        });
      }
      return baseGet(url, options);
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });
    await vi.waitFor(() => expect(view.host.querySelector('[role="status"]')?.textContent).toContain("运行中"), T);

    const rowByTitle = (title) => Array.from(view.host.querySelectorAll(".scn2-qrow"))
      .find(row => row.textContent.includes(title));
    await click(rowByTitle("回潮"));
    await vi.waitFor(() => expect(client.getLatestSceneRunJob.mock.calls.some(([sceneId]) => sceneId === "s2")).toBe(true), T);
    await click(rowByTitle("交班"));

    await vi.waitFor(() => {
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe(terminal);
    }, T);
    if (terminal === "completed") {
      await vi.waitFor(() => expect(client.apiGet.mock.calls.some(([url]) => url === "/api/v1/scenes/s1/workbench")).toBe(true), T);
    }
    await act(async () => { await Promise.resolve(); });
    expect(view.host.querySelector(".scn2-qrow.is-active .scn2-chip")?.textContent).toContain(expectedRow);
    expect(view.host.querySelector(".scn2-run")).toBeNull();
    if (expectReview) {
      expect(view.host.querySelector(".scn2-review")).toBeTruthy();
    }
  });

  it("clears stale running immediately while completed workbench recovery is still pending", async () => {
    const { mod, client } = await loadSceneRun({ projects: [NON_DEMO_PROJECT] });
    mod.scnRunSave("ch01s1", {
      state: "running",
      progress: 0.6,
      attempt: 1,
      draft: [],
      metrics: [],
      alignment: [],
      cost: [],
      log: [],
    });
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: "job-completed-pending-workbench",
      scene_id: "s1",
      status: "completed",
    });
    let workbenchSignal = null;
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url, { signal } = {}) => {
      if (url !== "/api/v1/scenes/s1/workbench" || !signal) return baseGet(url);
      workbenchSignal = signal;
      return new Promise((resolve, reject) => {
        void resolve;
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });

    await vi.waitFor(() => {
      expect(workbenchSignal).toBeTruthy();
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe("completed");
      expect(view.host.querySelector(".scn2-qrow.is-active .scn2-chip")?.textContent).toContain("排队");
      expect(view.host.querySelector(".scn2-run")).toBeNull();
      expect(view.host.textContent).toContain("正在恢复产出");
    }, T);

    await view.unmount();
    expect(workbenchSignal.aborted).toBe(true);
  });

  it.each([
    { cachedState: "ready", expectedLabel: "待复核", rejectWorkbench: true },
    { cachedState: "archived", expectedLabel: "已归档", rejectWorkbench: false },
  ])("preserves a usable cached $cachedState result when completed workbench recovery has no data", async ({ cachedState, expectedLabel, rejectWorkbench }) => {
    const { mod, client } = await loadSceneRun({ projects: [NON_DEMO_PROJECT] });
    const cached = {
      ...mod.scnQC([{ id: "p1", beat: "goal", text: "潮水退去，她留下了证词。" }], false),
      state: cachedState,
      progress: 1,
      attempt: 1,
      attempts: [],
      cost: [],
      log: [],
    };
    mod.scnRunSave("ch01s1", cached);
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockResolvedValue({
      job_id: `job-cached-${cachedState}`,
      scene_id: "s1",
      status: "completed",
    });
    const baseGet = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url, options) => {
      if (url !== "/api/v1/scenes/s1/workbench") return baseGet(url, options);
      return rejectWorkbench ? Promise.reject(new Error("temporary network")) : Promise.resolve({});
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });

    await vi.waitFor(() => {
      expect(client.apiGet.mock.calls.some(([url]) => url === "/api/v1/scenes/s1/workbench")).toBe(true);
      expect(view.host.querySelector('[data-testid="scene-run-job-control"]')?.dataset.status).toBe("completed");
      expect(view.host.querySelector(".scn2-qrow.is-active .scn2-chip")?.textContent).toContain(expectedLabel);
      expect(view.host.querySelector(".scn2-run")).toBeNull();
    }, T);
    expect(mod.scnRunLoad("ch01s1")).toMatchObject({ state: cachedState });
    expect(mod.scnRunLoad("ch01s1").draft.length).toBeGreaterThan(0);
  });

  it("stops the real page progress timer and scnRun polling after unmount", async () => {
    const { client } = await loadSceneRun();
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockRejectedValue(
      Object.assign(new Error("not found"), { status: 404, code: "RUN_JOB_NOT_FOUND" }),
    );
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/run\/jobs$/.test(url)) {
        return Promise.resolve({ job_id: "job-unmount", scene_id: "s1", status: "running" });
      }
      return Promise.resolve({});
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });
    await vi.waitFor(() => {
      const start = Array.from(view.host.querySelectorAll("button"))
        .find((button) => button.textContent.includes("开始起草"));
      expect(start).toBeTruthy();
    }, T);
    const start = Array.from(view.host.querySelectorAll("button"))
      .find((button) => button.textContent.includes("开始起草"));
    await click(start);
    await vi.waitFor(() => {
      expect(client.apiPost).toHaveBeenCalledWith(
        "/api/v1/scenes/s1/run/jobs",
        { run_policy: "strict" },
        expect.objectContaining({ signal: expect.anything() }),
      );
    }, T);

    await view.unmount();
    client.apiGet.mockClear();
    await new Promise((resolve) => setTimeout(resolve, 2100));

    const stalePolls = client.apiGet.mock.calls.filter(([url]) => url === "/api/v1/run-jobs/job-unmount");
    expect(stalePolls).toEqual([]);
  });

  it("aborts a pending create-job POST when the real page unmounts", async () => {
    const { client } = await loadSceneRun();
    window.__scnEnqueue = { sid: "ch01s1" };
    client.getLatestSceneRunJob.mockRejectedValue(
      Object.assign(new Error("not found"), { status: 404, code: "RUN_JOB_NOT_FOUND" }),
    );
    let postSignal = null;
    client.apiPost.mockImplementation((url, body, { signal } = {}) => {
      if (!/\/api\/v1\/scenes\/s1\/run\/jobs$/.test(url)) return Promise.resolve({});
      void body;
      postSignal = signal;
      return new Promise((resolve, reject) => {
        void resolve;
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    });
    const page = await import("./ws-scene.jsx");
    const view = await renderRunJobControl(page.WsScene, { go: vi.fn(), t: {} });
    await vi.waitFor(() => expect(Array.from(view.host.querySelectorAll("button"))
      .some(button => button.textContent.includes("开始起草"))).toBe(true), T);
    const start = Array.from(view.host.querySelectorAll("button"))
      .find(button => button.textContent.includes("开始起草"));
    await click(start);
    await vi.waitFor(() => expect(postSignal).toBeTruthy(), T);

    await view.unmount();

    expect(postSignal.aborted).toBe(true);
  });
});

describe("scnBackendQueueSids（队列成员的后端派生）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("run-states 按目录 backendId 对位成 sid 列表；无对位的场丢弃", async () => {
    const { mod, client } = await loadSceneRun();
    // 等目录装载（派生依赖 backendId → sid 映射）
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    routeRunStates(client, () =>
      Promise.resolve({
        items: [
          { scene_id: "s1", scene_status: "human_review_required" },
          { scene_id: "s-ghost", scene_status: "archived" }, // 目录里没有：丢弃
        ],
      })
    );

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual(["ch01s1"]);
    expect(client.apiGet).toHaveBeenCalledWith("/api/v1/scene-run-states?project_id=tide");
  });

  it("目录为空时先 __refresh 再对位（换浏览器冷启动路径）", async () => {
    // 启动装载吃到空目录（installApiRouter 的 catalog: []）；之后经包装路由
    // 返回真实章——模拟「目录还没就绪就进起草台」的竞态，派生应自行补拉
    const { mod, client } = await loadSceneRun({ catalog: [] });
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.ready()).toBe(true), T);
    expect(cat.WsCatalog.get().length).toBe(0);
    const base = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (RUN_STATES_URL.test(url)) {
        return Promise.resolve({ items: [{ scene_id: "s1", scene_status: "soft_qc_patch_required" }] });
      }
      if (/\/api\/v2\/projects\/[^/]+\/catalog(\?|$)/.test(url)) {
        return Promise.resolve({ chapters: [DEFAULT_CHAP] });
      }
      return base(url);
    });

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual(["ch01s1"]);
  });

  it("run-states 端点失败时返回空列表（本地队列照常可用，不炸）", async () => {
    const { mod, client } = await loadSceneRun();
    routeRunStates(client, () => Promise.reject(new Error("boom")));

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual([]);
  });
});

/* ==========================================================
   Wave 1（结果闭环治理 §5.2）：采纳归档必须先打后端单入口。
   旧实现 scnAdoptToDoc 只写 wr-doc 缓存 + 目录置 done——前端「完成」
   与后端归档态可以分裂（G-02）。新契约：
   · 成功路径 = POST /scenes/{id}/adopt-current 成功 → 才写缓存/置 done
   · 后端拒绝（无稿/来源安全）→ 不置 done、不写缓存，faithful 返回失败
   ========================================================== */
describe("scnAdoptToDoc（归档单入口：先后端、后本地）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => vi.restoreAllMocks());

  const DRAFT = [{ id: "p1", beat: null, parts: [{ text: "潮水退去，她看清了闸门上的名字。" }] }];

  async function loadWithCatalog(opts) {
    const { mod, client } = await loadSceneRun(opts);
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    return { mod, client, cat };
  }

  it("成功：POST adopt-current 后才置 done + 写正文缓存", async () => {
    const { mod, client, cat } = await loadWithCatalog();
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/adopt-current$/.test(url)) {
        return Promise.resolve({ scene_id: "s1", scene_status: "archived", final_scene_row_id: "final_s1_v1" });
      }
      return Promise.resolve({});
    });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT);

    expect(result.ok).toBe(true);
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/adopt-current", expect.anything());
    // done 只由服务端 archived 响应映射，且写穿到目录 PATCH（mock 后端重拉
    // 会把乐观缓存收敛回 mock 值，故断言写穿动作而非最终缓存态）
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      expect.stringMatching(/\/scenes\/s1$/),
      expect.objectContaining({ state: "done" })
    ), T);
    void cat;
    // 正文写作器缓存同步（写穿主路径或缓存）
    const wrKeys = Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"));
    expect(wrKeys.length).toBeGreaterThan(0);
  });

  it("后端拒绝（409 无稿/来源安全）：不置 done、不写缓存、faithful 返回失败", async () => {
    const { mod, client, cat } = await loadWithCatalog();
    const blocked = Object.assign(new Error("blocked"), { code: "SOURCE_SAFETY_BLOCKED" });
    client.apiPost.mockImplementation((url) => {
      if (/\/adopt-current$/.test(url)) return Promise.reject(blocked);
      return Promise.resolve({});
    });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT);

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("SOURCE_SAFETY_BLOCKED");
    // 可证伪：先本地置 done 的旧实现会发出 state:"done" 的目录 PATCH，此断言转红
    const donePatches = client.apiPatch.mock.calls.filter(c => c[1] && c[1].state === "done");
    expect(donePatches).toEqual([]);
    const scene = cat.WsCatalog.get()[0].scenes.find(s => s.sid === "ch01s1");
    expect(scene.state).not.toBe("done");
    expect(Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"))).toEqual([]);
  });

  it("目录未同步到后端（无 backendId）：不静默装成功", async () => {
    const { mod } = await loadSceneRun({ catalog: [] });
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.ready()).toBe(true), T);
    const result = await mod.scnAdoptToDoc("ch99s9", DRAFT);
    expect(result.ok).toBe(false);
  });
});

/* ==========================================================
   Wave 2（结果闭环治理 §5.3/§5.4）：作者可见状态门。
   「无法继续」（hard_blocked = verified Q0/Q1，不可归档）与
   「已有稿但建议修改」（quality_warning = Q2/Q3，可归档）必须分开：
   · scnGateFrom 从 workbench/status 的 author_state 投影提取 gate
   · scnAdoptToDoc 对 canArchive=false 前置拦截（不发 adopt POST）
   · quality_warning 不拦归档
   ========================================================== */
describe("作者状态门（Wave 2：无法继续 vs 有稿建议修改）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => vi.restoreAllMocks());

  const DRAFT = [{ id: "p1", beat: null, parts: [{ text: "潮水退去，她看清了闸门上的名字。" }] }];

  const HARD_BLOCKED_PROJECTION = {
    author_state: "hard_blocked",
    blocking_findings: [{ issue_key: "missing_required_text", quality_level: "Q1", verified_by: "scene_card_required_text" }],
    quality_warnings: [],
    recommended_actions: ["review_pipeline_gate"],
    can_archive: false,
  };
  const QUALITY_WARNING_PROJECTION = {
    author_state: "quality_warning",
    blocking_findings: [],
    quality_warnings: [{ issue_key: "pacing_flat", quality_level: "Q2" }],
    recommended_actions: ["adopt_or_patch"],
    can_archive: true,
  };

  it("scnGateFrom：hard_blocked 投影 → canArchive=false + 阻断条目", async () => {
    const { mod } = await loadSceneRun();
    const gate = mod.scnGateFrom({ author_state: HARD_BLOCKED_PROJECTION });
    expect(gate.authorState).toBe("hard_blocked");
    expect(gate.canArchive).toBe(false);
    expect(gate.blocking[0].issue_key).toBe("missing_required_text");
  });

  it("hard QC rewrite_brief becomes an actionable author rewrite instruction", async () => {
    const { mod } = await loadSceneRun();
    expect(mod.scnRewriteBriefFrom({
      hard_qc: { rewrite_brief: ["补齐推门动作", "明确主动销毁通行证"] },
      author_state: HARD_BLOCKED_PROJECTION,
    })).toBe("补齐推门动作；明确主动销毁通行证");
  });

  it("scnGateFrom：quality_warning 投影 → 可归档 + 警告随行；无投影 → null", async () => {
    const { mod } = await loadSceneRun();
    const gate = mod.scnGateFrom({ author_state: QUALITY_WARNING_PROJECTION });
    expect(gate.authorState).toBe("quality_warning");
    expect(gate.canArchive).toBe(true);
    expect(gate.warnings.length).toBe(1);
    expect(mod.scnGateFrom({})).toBeNull();
  });

  it("scnAdoptToDoc：gate 不可归档 → 前置拦截，不发 adopt-current POST", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const gate = mod.scnGateFrom({ author_state: HARD_BLOCKED_PROJECTION });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT, gate);

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("Q0/Q1");
    const adoptCalls = client.apiPost.mock.calls.filter(c => /adopt-current/.test(c[0]));
    expect(adoptCalls).toEqual([]);
    // 正文保留、不置 done、不写缓存
    expect(Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"))).toEqual([]);
  });

  it("Wave 3 终选三函数：盲化取数 / 选择提交 / 续跑（sid→后端 id 对位）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const base = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/style-candidates$/.test(url)) {
        return Promise.resolve({
          blinded: true,
          candidates: [
            { row_id: "cand_b", content: "候选乙全文" },
            { row_id: "cand_a", content: "候选甲全文" },
          ],
          selection: { decision_status: "awaiting", selected_row_id: null },
        });
      }
      return base(url);
    });
    client.apiPost.mockImplementation((url) => Promise.resolve({ ok: true, url }));

    const list = await mod.scnCandidates("ch01s1");
    // 盲化契约：按后端 blinded_order 原样呈现，不重排、无分数字段
    expect(list.blinded).toBe(true);
    expect(list.candidates.map(c => c.row_id)).toEqual(["cand_b", "cand_a"]);
    expect(list.candidates.every(c => !("adversarial_score" in c))).toBe(true);

    await mod.scnSelectCandidate("ch01s1", "cand_b", { no_clear_difference: true });
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/s1/style-candidates/cand_b/select",
      expect.objectContaining({ no_clear_difference: true })
    );

    await mod.scnResumeAfterSelection("ch01s1");
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/resume-after-selection", expect.anything());
  });

  it("Wave 3 终选锁定：SELECTION_LOCKED 拒绝原样上抛（不静默吞掉）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const locked = Object.assign(new Error("selection locked"), { code: "SELECTION_LOCKED" });
    client.apiPost.mockImplementation((url) => {
      if (/\/select$/.test(url)) return Promise.reject(locked);
      return Promise.resolve({});
    });

    await expect(mod.scnSelectCandidate("ch01s1", "cand_x", {})).rejects.toMatchObject({ code: "SELECTION_LOCKED" });
  });

  it("scnAdoptToDoc：quality_warning 的 gate 不拦归档（Q2/Q3 照常交付）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    client.apiPost.mockImplementation((url) => {
      if (/adopt-current$/.test(url)) {
        return Promise.resolve({ scene_id: "s1", scene_status: "archived", final_scene_row_id: "final_s1_v1" });
      }
      return Promise.resolve({});
    });
    const gate = mod.scnGateFrom({ author_state: QUALITY_WARNING_PROJECTION });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT, gate);

    expect(result.ok).toBe(true);
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/adopt-current", expect.anything());
  });
});
