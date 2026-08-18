import { describe, expect, it } from "vitest";
import { manuscriptToDocHTML, sanitizeManuscriptHTML } from "./manuscript-html.js";


describe("manuscript HTML trust boundary", () => {
  it("removes scripts, event handlers, remote media and embedded documents", () => {
    const dirty = '<p onclick="steal()">正文<img src=x onerror="steal()"></p>'
      + '<script>steal()</script><iframe src="https://evil.invalid"></iframe>';
    expect(sanitizeManuscriptHTML(dirty)).toBe("<p>正文</p>");
  });

  it("keeps the editor formatting vocabulary without user attributes", () => {
    expect(sanitizeManuscriptHTML('<blockquote class="x"><strong style="x">句子</strong><br></blockquote>'))
      .toBe("<blockquote><strong>句子</strong><br></blockquote>");
  });

  it("escapes plain text before wrapping it in paragraphs", () => {
    expect(manuscriptToDocHTML("A & B\n1 < 2"))
      .toBe("<p>A &amp; B</p><p>1 &lt; 2</p>");
  });
});
