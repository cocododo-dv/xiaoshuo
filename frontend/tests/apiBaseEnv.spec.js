// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

describe("api base defaults", () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("uses the Vite-provided backend URL when local storage has no override", async () => {
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8052");
    vi.resetModules();

    const api = await import("../src/lib/api/index.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8052");
    expect(api.setApiBase("")).toBe("http://127.0.0.1:8052");
  });

  it("replaces a stale 8000 local storage default when the dev server injects a different backend URL", async () => {
    localStorage.setItem("novel-system-api-base", "http://127.0.0.1:8000");
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8052");
    vi.resetModules();

    const api = await import("../src/lib/api/index.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8052");
    expect(localStorage.getItem("novel-system-api-base")).toBe("http://127.0.0.1:8052");
  });

  it("replaces a stale prior dev-server default when the injected backend URL changes again", async () => {
    localStorage.setItem("novel-system-api-base", "http://127.0.0.1:8052");
    localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8052");
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8000");
    vi.resetModules();

    const api = await import("../src/lib/api/index.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8000");
    expect(localStorage.getItem("novel-system-api-base")).toBe("http://127.0.0.1:8000");
  });

  it("replaces a stale local dev URL from older builds that did not record the injected default", async () => {
    localStorage.setItem("novel-system-api-base", "http://127.0.0.1:8052");
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8000");
    vi.resetModules();

    const api = await import("../src/lib/api/index.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8000");
    expect(localStorage.getItem("novel-system-api-base")).toBe("http://127.0.0.1:8000");
  });

  it("keeps an explicit custom API base instead of replacing it with the dev-server default", async () => {
    localStorage.setItem("novel-system-api-base", "https://api.example.test");
    localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8052");
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8000");
    vi.resetModules();

    const api = await import("../src/lib/api/index.js");

    expect(api.getApiBase()).toBe("https://api.example.test");
    expect(localStorage.getItem("novel-system-api-base")).toBe("https://api.example.test");
  });

  it("surfaces API request ids and sends a client trace id on mutations", async () => {
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8052");
    vi.resetModules();
    const api = await import("../src/lib/api/index.js");

    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        ok: false,
        data: null,
        error: {
          code: "VALIDATION_FAILED",
          message: "缺少标题",
          details: { retryable: false, field: "title" },
        },
        request_id: "req_visible_123",
      }),
    }));

    await expect(api.apiPost("/api/v2/projects", {})).rejects.toMatchObject({
      name: "ApiRequestError",
      message: "缺少标题",
      code: "VALIDATION_FAILED",
      status: 422,
      requestId: "req_visible_123",
      retryable: false,
      details: { retryable: false, field: "title" },
    });

    const headers = globalThis.fetch.mock.calls[0][1].headers;
    expect(headers["X-Client-Request-Id"]).toMatch(/^client_/);
  });
});
