// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";

import FlowActionReceipt from "../src/components/FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../src/composables/useFlowActionFeedback";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function mountReceipt(receipt, props = {}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp({
    render() {
      return h(FlowActionReceipt, {
        receipt,
        ...props,
      });
    },
  });
  app.mount(host);
  return {
    host,
    unmount() {
      app.unmount();
      host.remove();
    },
  };
}

describe("flow action feedback", () => {
  it("records running and success receipts while still emitting a notice", async () => {
    const notices = [];
    const pending = deferred();
    const { runFlowAction, receiptFor, isRunning } = useFlowActionFeedback({
      emitNotice: (message) => notices.push(message),
    });

    const runPromise = runFlowAction({
      scopeKey: "reference:apply:alpha",
      actionLabel: "应用到审核",
      runningMessage: "正在创建应用审核项...",
      successMessage: (result) => `已创建 ${result.reviewCount} 个应用审核项。`,
      nextStep: () => "下一步：去审核收件箱确认。",
      action: async () => {
        await pending.promise;
        return { reviewCount: 2 };
      },
    });

    expect(isRunning("reference:apply:alpha").value).toBe(true);
    expect(receiptFor("reference:apply:alpha").value).toMatchObject({
      status: "running",
      actionLabel: "应用到审核",
      message: "正在创建应用审核项...",
    });

    pending.resolve();
    const result = await runPromise;

    expect(result).toEqual({ reviewCount: 2 });
    expect(isRunning("reference:apply:alpha").value).toBe(false);
    expect(receiptFor("reference:apply:alpha").value).toMatchObject({
      status: "success",
      actionLabel: "应用到审核",
      message: "已创建 2 个应用审核项。",
      nextStep: "下一步：去审核收件箱确认。",
    });
    expect(notices).toEqual(["已创建 2 个应用审核项。"]);
  });

  it("records a failure receipt when an action rejects", async () => {
    const notices = [];
    const { runFlowAction, receiptFor } = useFlowActionFeedback({
      emitNotice: (message) => notices.push(message),
    });

    const result = await runFlowAction({
      scopeKey: "system:save",
      actionLabel: "保存配置",
      runningMessage: "正在保存配置...",
      successMessage: () => "已保存配置。",
      nextStep: () => "下一步：继续检查路由。",
      action: async () => {
        throw new Error("配置写入失败");
      },
    });

    expect(result).toBeNull();
    expect(receiptFor("system:save").value).toMatchObject({
      status: "error",
      actionLabel: "保存配置",
      message: "配置写入失败",
      nextStep: "检查输入后可重试。",
    });
    expect(notices).toEqual(["配置写入失败"]);
  });

  it("renders receipt states, next steps, and navigation actions without raw layout breaks", async () => {
    const onNavigate = vi.fn();
    const receipt = {
      status: "success",
      actionLabel: "应用到审核",
      message:
        "已创建审核项 review_apply_refprofile_refbook_d4ae8e00eea8_c172c96ee5_extra_long_identifier_for_layout_testing。",
      nextStep: "下一步：去审核收件箱确认。",
      target: { label: "去审核收件箱", view: "review" },
    };
    const { host, unmount } = mountReceipt(receipt, { onNavigate });

    expect(host.querySelector('[data-testid="flow-action-receipt"]').textContent).toContain("成功");
    expect(host.textContent).toContain("应用到审核");
    expect(host.textContent).toContain("下一步：去审核收件箱确认。");
    expect(host.querySelector(".flow-action-message").textContent).toContain("review_apply_refprofile");
    expect(host.querySelector(".flow-action-message").className).toContain("flow-action-message");

    host.querySelector('[data-testid="flow-action-target"]').click();
    await nextTick();
    expect(onNavigate).toHaveBeenCalledWith(receipt.target);

    unmount();
  });
});
