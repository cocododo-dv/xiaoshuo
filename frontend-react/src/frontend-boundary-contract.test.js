import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";


const srcRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.dirname(srcRoot);


describe("frontend security, navigation, and accessibility boundaries", () => {
  it("records user navigation in browser history while keeping alias redirects replace-only", () => {
    const source = fs.readFileSync(path.join(srcRoot, "ws-app.jsx"), "utf8");

    expect(source).toContain('history.pushState(null, "", "#" + v)');
    expect(source).toContain('history.replaceState(null, "", "#" + target)');
  });

  it("uses a keyboard-focusable button for the inbox navigation action", () => {
    const source = fs.readFileSync(path.join(srcRoot, "ws-home.jsx"), "utf8");

    expect(source).toContain('<button type="button" className="home-card-go home-card-go-btn"');
    expect(source).not.toContain('<span className="home-card-go home-card-go-btn"');
  });

  it("ships a local-only font path and a baseline content security policy", () => {
    const html = fs.readFileSync(path.join(projectRoot, "index.html"), "utf8");

    expect(html).toContain('http-equiv="Content-Security-Policy"');
    expect(html).toContain("object-src 'none'");
    expect(html).not.toContain("fonts.googleapis.com");
    expect(html).not.toContain("fonts.gstatic.com");
    expect(html).not.toContain("潮汐档案");
  });
});
