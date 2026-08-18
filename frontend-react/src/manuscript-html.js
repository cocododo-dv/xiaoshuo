const ALLOWED_MANUSCRIPT_TAGS = new Set([
  "P", "BR", "DIV", "SPAN", "STRONG", "B", "EM", "I", "U", "S", "STRIKE",
  "BLOCKQUOTE", "UL", "OL", "LI", "PRE", "CODE", "H1", "H2", "H3", "H4",
  "H5", "H6", "MARK", "SUB", "SUP",
]);

const DROP_WITH_CONTENT = new Set([
  "SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "SVG", "MATH", "TEMPLATE", "NOSCRIPT",
]);

const DROP_EMPTY = new Set([
  "IMG", "AUDIO", "VIDEO", "SOURCE", "TRACK", "LINK", "META", "BASE", "INPUT",
]);

export function escapeManuscriptText(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function sanitizeManuscriptHTML(value) {
  const raw = String(value == null ? "" : value);
  if (!raw || !raw.includes("<")) return raw;
  if (typeof document === "undefined") return escapeManuscriptText(raw);

  const template = document.createElement("template");
  template.innerHTML = raw;
  const clean = (parent) => {
    Array.from(parent.childNodes).forEach((node) => {
      if (node.nodeType !== 1) return;
      const tag = node.tagName;
      if (DROP_WITH_CONTENT.has(tag) || DROP_EMPTY.has(tag)) {
        node.remove();
        return;
      }
      clean(node);
      if (!ALLOWED_MANUSCRIPT_TAGS.has(tag)) {
        node.replaceWith(...Array.from(node.childNodes));
        return;
      }
      Array.from(node.attributes).forEach(attr => node.removeAttribute(attr.name));
    });
  };
  clean(template.content);
  return template.innerHTML;
}

export function manuscriptToDocHTML(value) {
  const content = String(value == null ? "" : value);
  if (!content) return "";
  if (/<\w+[^>]*>/.test(content)) return sanitizeManuscriptHTML(content);
  return content
    .split(/\n+/)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => `<p>${escapeManuscriptText(line)}</p>`)
    .join("");
}
