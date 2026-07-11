/* global window */
/* ==========================================================
   WsManuStore — 成稿中心正文 store（Wave 1 · 结果闭环治理 §5.2）
   ----------------------------------------------------------
   唯一正文来源 = 后端章节聚合（GET /api/v1/chapter-manuscripts/{chapter_id}，
   服务端以 FinalScene 归档行为源）。localStorage 的 wr-doc:* 是写作器的
   编辑缓存，不再作为「成稿」来源——清缓存不丢稿的前提是稿在后端。
   形态同其余 store：同步内存缓存 + 异步 refresh，视图零等待读 body()。
   键 = 后端 chapter_id（目录卡的 backendId），不是 FE slug。
   ========================================================== */

import { apiGet } from "./lib/client.js";

// chapterBackendId → { detail } | { error: true }
const manuCache = {};
const manuInflight = {};

function toParas(content) {
  return String(content || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

const WsManuStore = {
  /** 拉后端章节聚合（幂等去重并发）；失败缓存 error 标记，body() 返回 null。 */
  async refresh(chapterId) {
    if (!chapterId) return null;
    if (manuInflight[chapterId]) return manuInflight[chapterId];
    manuInflight[chapterId] = (async () => {
      try {
        const detail = await apiGet(`/api/v1/chapter-manuscripts/${chapterId}`);
        manuCache[chapterId] = { detail };
      } catch (e) {
        manuCache[chapterId] = { error: true };
      } finally {
        delete manuInflight[chapterId];
        try { window.dispatchEvent(new CustomEvent("ws:manuscripts-loaded", { detail: chapterId })); } catch (e) {}
      }
      return manuCache[chapterId];
    })();
    return manuInflight[chapterId];
  },

  /** 同步读：{ completion, assembled, aggregate, scenes:[{sceneId, paras, live, charCount}] } | null */
  body(chapterId) {
    const hit = manuCache[chapterId];
    if (!hit || hit.error || !hit.detail) return null;
    const detail = hit.detail;
    const scenes = (detail.scenes || []).map((entry) => {
      const finalScene = entry.final_scene;
      const live = !!(finalScene && (finalScene.content || "").trim());
      return {
        sceneId: entry.scene_id,
        sceneSeq: entry.scene_seq,
        live,
        paras: live ? toParas(finalScene.content) : [],
        charCount: finalScene ? finalScene.char_count || 0 : 0,
      };
    });
    return {
      completion: detail.completion_status || "empty",
      assembled: detail.assembled || null,
      aggregate: detail.aggregate || null,
      missingSceneIds: (detail.assembled && detail.assembled.missing_scene_ids) || [],
      scenes,
    };
  },

  /** 是否有已装载的数据（区分 loading 与真无稿） */
  loaded(chapterId) {
    return !!manuCache[chapterId];
  },

  /** 作品切换/归档后失效重拉 */
  invalidate(chapterId) {
    if (chapterId) { delete manuCache[chapterId]; }
    else { Object.keys(manuCache).forEach((k) => delete manuCache[k]); }
  },
};

Object.assign(window, { WsManuStore });

export { WsManuStore };
