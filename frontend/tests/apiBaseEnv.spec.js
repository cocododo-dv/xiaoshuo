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

    const api = await import("../src/lib/api.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8052");
    expect(api.setApiBase("")).toBe("http://127.0.0.1:8052");
  });

  it("replaces a stale 8000 local storage default when the dev server injects a different backend URL", async () => {
    localStorage.setItem("novel-system-api-base", "http://127.0.0.1:8000");
    vi.stubEnv("VITE_NOVEL_SYSTEM_API_BASE", "http://127.0.0.1:8052");
    vi.resetModules();

    const api = await import("../src/lib/api.js");

    expect(api.getApiBase()).toBe("http://127.0.0.1:8052");
    expect(localStorage.getItem("novel-system-api-base")).toBe("http://127.0.0.1:8052");
  });
});
