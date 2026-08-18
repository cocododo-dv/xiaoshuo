import { describe, expect, it } from "vitest";

import { wrPickedText, wrPlainText, wrSentences } from "./writer-candidates.js";


describe("writer candidate sentence adoption", () => {
  it("decodes escaped prose entities before inserting selected sentences", () => {
    const sentences = wrSentences(
      "第一句 A &amp; B。第二句金额 &lt; 100，符号 &gt; 0！",
    );

    expect(wrPickedText(sentences, [1, 0])).toBe(
      "第一句 A & B。第二句金额 < 100，符号 > 0！",
    );
  });

  it("keeps marked prose as plain text without leaking markup", () => {
    expect(wrPlainText("<mark>潮水</mark> &amp; 月光")).toBe("潮水 & 月光");
  });
});
