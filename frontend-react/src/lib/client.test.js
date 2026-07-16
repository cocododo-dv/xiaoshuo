import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiGet, setRemoteAccessToken } from "./client.js";


describe("remote access token transport", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: { status: "ok" } }),
    });
  });

  afterEach(() => {
    setRemoteAccessToken("");
    vi.restoreAllMocks();
  });

  it("sends the explicitly configured token without persisting it to localStorage", async () => {
    setRemoteAccessToken("remote-secret");

    await apiGet("/ready");

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers["X-Novel-Access-Token"]).toBe("remote-secret");
    expect(window.localStorage.getItem("novel-system-remote-access-token")).toBeNull();
  });
});
