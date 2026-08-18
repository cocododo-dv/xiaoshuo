export function wrSentences(html) {
  return String(html || "").split(/(?<=[。！？!?])/g).filter((sentence) => sentence.trim());
}

export function wrPlainText(html) {
  const parsed = new DOMParser().parseFromString(String(html || ""), "text/html");
  return parsed.body.textContent || "";
}

export function wrPickedText(sentences, picked) {
  return picked
    .slice()
    .sort((left, right) => left - right)
    .map((index) => wrPlainText(sentences[index]))
    .join("");
}
