const nodeCrypto = require("node:crypto");
if (typeof nodeCrypto.getRandomValues !== "function") {
  nodeCrypto.getRandomValues = nodeCrypto.webcrypto.getRandomValues.bind(nodeCrypto.webcrypto);
}
if (typeof globalThis.crypto === "undefined" || typeof globalThis.crypto.getRandomValues !== "function") {
  globalThis.crypto = nodeCrypto.webcrypto;
}

// Node 16 缺 ES2023 数组方法；jsdom 依赖链（css-color）在 vitest 里会用到。
if (typeof Array.prototype.findLastIndex !== "function") {
  Object.defineProperty(Array.prototype, "findLastIndex", {
    value(predicate, thisArg) {
      for (let i = this.length - 1; i >= 0; i--) {
        if (predicate.call(thisArg, this[i], i, this)) return i;
      }
      return -1;
    },
    writable: true,
    configurable: true,
  });
}
if (typeof Array.prototype.findLast !== "function") {
  Object.defineProperty(Array.prototype, "findLast", {
    value(predicate, thisArg) {
      const i = this.findLastIndex(predicate, thisArg);
      return i === -1 ? undefined : this[i];
    },
    writable: true,
    configurable: true,
  });
}
