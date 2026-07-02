const nodeCrypto = require("node:crypto");
if (typeof nodeCrypto.getRandomValues !== "function") {
  nodeCrypto.getRandomValues = nodeCrypto.webcrypto.getRandomValues.bind(nodeCrypto.webcrypto);
}
if (typeof globalThis.crypto === "undefined" || typeof globalThis.crypto.getRandomValues !== "function") {
  globalThis.crypto = nodeCrypto.webcrypto;
}
