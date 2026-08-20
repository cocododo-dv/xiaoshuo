// @vitest-environment jsdom
//
// PR-5 — lib/api/styleReference.js URL 拼装 + headers + body 形状测试。
// 全部用 vi.spyOn(global, "fetch") 拦截真实请求,不依赖后端。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as sr from "../src/lib/api/styleReference";

function jsonResponse(data, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => ({ ok, data, error: ok ? null : data, request_id: "req_test" }),
  };
}

const calls = [];

beforeEach(() => {
  calls.length = 0;
  vi.spyOn(global, "fetch").mockImplementation((url, init = {}) => {
    calls.push({ url, init });
    return Promise.resolve(jsonResponse({}));
  });
  // Localstorage 提供 API base
  if (typeof window !== "undefined") {
    window.localStorage.setItem("novel-system-api-base", "http://127.0.0.1:8000");
    window.localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("styleReference API client URL 拼装", () => {
  it("importBookPath POST /api/v2/style-reference/books/import-path", async () => {
    const rightsDeclaration = { analysis_rights: true, send_rights: true, declared_by: "测试用户" };
    await sr.importStyleReferenceBookPath({
      file_path: "x.txt",
      title: "t",
      cloud_policy: "segments_only",
      rights_declaration: rightsDeclaration,
    });
    expect(calls[0].url).toBe("http://127.0.0.1:8000/api/v2/style-reference/books/import-path");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.headers["X-Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(calls[0].init.body).rights_declaration).toEqual(rightsDeclaration);
  });

  it("listBooks GET 含 status query", async () => {
    await sr.listStyleReferenceBooks({ status: "ready" });
    expect(calls[0].url).toBe("http://127.0.0.1:8000/api/v2/style-reference/books?status=ready");
  });

  it("getBook URL 编码 book_id", async () => {
    await sr.fetchStyleReferenceBook("sr_book_abc");
    expect(calls[0].url).toBe("http://127.0.0.1:8000/api/v2/style-reference/books/sr_book_abc");
  });

  it("deleteBook DELETE method + idempotency header", async () => {
    await sr.deleteStyleReferenceBook("sr_book_abc");
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].init.headers["X-Idempotency-Key"]).toBeTruthy();
  });

  it("importBookUpload 用 FormData(无 Content-Type 自动 boundary)", async () => {
    const file = new File(["text"], "a.txt", { type: "text/plain" });
    const rightsDeclaration = { analysis_rights: true, send_rights: true, declared_by: "测试用户" };
    await sr.importStyleReferenceBookUpload({
      file,
      title: "t",
      authorLabel: "a",
      cloudPolicy: "segments_only",
      rightsDeclaration,
    });
    expect(calls[0].url).toContain("/import-upload");
    expect(calls[0].init.body).toBeInstanceOf(FormData);
    expect(calls[0].init.headers["Content-Type"]).toBeUndefined();
    expect(calls[0].init.body.get("rights_declaration")).toBe(JSON.stringify(rightsDeclaration));
  });

  it("startRun POST with layers payload", async () => {
    await sr.startStyleReferenceRun("sr_book_1", { layers: ["language", "narrative"] });
    expect(calls[0].url).toContain("/books/sr_book_1/runs");
    expect(JSON.parse(calls[0].init.body)).toEqual({ layers: ["language", "narrative"] });
  });

  it("startRun 不传 layers 时 body 为空对象(PR-23 默认值在后端)", async () => {
    await sr.startStyleReferenceRun("sr_book_1");
    expect(JSON.parse(calls[0].init.body)).toEqual({});
  });

  it("listRunFindings include=evidence 透传(PR-23)", async () => {
    await sr.listStyleReferenceRunFindings("sr_run_x", { include: "evidence" });
    expect(calls[0].url).toContain("include=evidence");
  });

  it("listRunFindings query string 组装", async () => {
    await sr.listStyleReferenceRunFindings("sr_run_x", {
      subDimension: "language.rhetoric",
      findingKind: "observation",
      status: "pending",
    });
    expect(calls[0].url).toContain("sub_dimension=language.rhetoric");
    expect(calls[0].url).toContain("finding_kind=observation");
    expect(calls[0].url).toContain("status=pending");
  });

  it("reviewFinding POST payload", async () => {
    await sr.reviewStyleReferenceFinding("sr_find_x", { decision: "approved", comment: "ok" });
    expect(calls[0].url).toContain("/findings/sr_find_x/review");
    expect(JSON.parse(calls[0].init.body)).toEqual({ decision: "approved", comment: "ok" });
  });

  it("applyProfile POST snake_case payload", async () => {
    await sr.applyStyleReferenceProfile("sr_profile_x", {
      scope: "scene",
      scopeRefId: "scene_1",
      taskType: "scene_generation",
      strategy: "A",
    });
    expect(JSON.parse(calls[0].init.body)).toEqual({
      scope: "scene",
      scope_ref_id: "scene_1",
      task_type: "scene_generation",
      strategy: "A",
    });
  });

  it("applyProfile forwards MIXED controls instead of dropping them", async () => {
    await sr.applyStyleReferenceProfile("sr_profile_x", {
      scope: "project",
      strategy: "mixed",
      intensity: 80,
      subDimensions: ["language.punctuation"],
      includePositive: true,
      includeForbidden: true,
      includeMetric: true,
    });
    expect(JSON.parse(calls[0].init.body)).toEqual({
      scope: "project",
      scope_ref_id: null,
      task_type: "scene_generation",
      strategy: "mixed",
      intensity: 80,
      sub_dimensions: ["language.punctuation"],
      include_positive: true,
      include_forbidden: true,
      include_metric: true,
    });
  });

  it("deleteBinding DELETE", async () => {
    await sr.deleteStyleReferenceBinding("sr_bind_1");
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].url).toContain("/bindings/sr_bind_1");
  });
});
