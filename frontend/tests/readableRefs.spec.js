import { describe, expect, it } from "vitest";

import {
  compactEntityOptions,
  formatChapterChoice,
  formatReadableTargetRef,
  formatSceneChoice,
  shortTechnicalRef,
} from "../src/lib/readableRefs.js";

describe("readable reference labels", () => {
  it("shortens technical references without losing the raw value", () => {
    const raw = "author_draft:author_draft_chapter_CDBQA_20260507152812_01_280895d337";
    const short = shortTechnicalRef(raw, 32);

    expect(short.length).toBeLessThanOrEqual(32);
    expect(short).toContain("...");
    expect(short).toMatch(/^author_draft/);
    expect(short).toMatch(/895d337$/);
  });

  it("formats chapter and scene choices as compact author-facing labels", () => {
    const chapter = formatChapterChoice({
      chapter_id: "CDBQA_20260507152812_01",
      chapter_goal: "第一章：零点玻璃雨落在未来失踪名单上，城市档案修复师沈闻发现记录并非预言，而是有人提前写入的失踪顺序。",
    });
    const scene = formatSceneChoice({
      scene_id: "CDBQA_20260507152812_01_SC01",
      scene_goal: "废线站里，倒放广播证明失踪记录被人篡改。",
    });

    expect(chapter.label).toBe("第一章：零点玻璃雨落在未来失踪名单上");
    expect(chapter.raw).toBe("CDBQA_20260507152812_01");
    expect(chapter.technical).toContain("CDBQA_202605");
    expect(scene.label).toBe("废线站里，倒放广播证明失踪记录被人篡改。");
    expect(scene.detail).toContain("场景");
  });

  it("keeps only the latest duplicate QA entity by default while preserving the selected item", () => {
    const rows = [
      { chapter_id: "CDBQA_20260507152812_01", chapter_goal: "第一章：零点玻璃雨落在未来失踪名单上" },
      { chapter_id: "CDBQA_20260507154537_01", chapter_goal: "第一章：零点玻璃雨落在未来失踪名单上" },
      { chapter_id: "CDBQA_20260507152812_02", chapter_goal: "第二章：沈闻和许照进入地下废线站" },
    ];

    const compact = compactEntityOptions(rows, {
      idKey: "chapter_id",
      titleKeys: ["chapter_goal"],
      selectedId: "CDBQA_20260507152812_01",
      formatter: formatChapterChoice,
    });

    expect(compact.options.map((item) => item.value)).toEqual([
      "CDBQA_20260507152812_01",
      "CDBQA_20260507154537_01",
      "CDBQA_20260507152812_02",
    ]);
    expect(compact.hiddenCount).toBe(0);

    const unselected = compactEntityOptions(rows, {
      idKey: "chapter_id",
      titleKeys: ["chapter_goal"],
      formatter: formatChapterChoice,
    });
    expect(unselected.options.map((item) => item.value)).toEqual([
      "CDBQA_20260507154537_01",
      "CDBQA_20260507152812_02",
    ]);
    expect(unselected.hiddenCount).toBe(1);
  });

  it("hides raw target references behind readable labels", () => {
    const readable = formatReadableTargetRef("calibration_line:chapter:CDBQA_20260507154537_01");

    expect(readable.label).toBe("校准句 / 章节");
    expect(readable.raw).toBe("calibration_line:chapter:CDBQA_20260507154537_01");
    expect(readable.technical).toContain("calibration_line");
  });
});
