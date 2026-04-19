const defaultApiBase = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;

export async function configureConnection(page, { apiBase = defaultApiBase, operatorRef = "operator" } = {}) {
  await page.evaluate(
    ({ nextApiBase, nextOperatorRef }) => {
      window.localStorage.setItem("novel-system-api-base", nextApiBase);
      window.localStorage.setItem("novel-system-operator-ref", nextOperatorRef);
    },
    { nextApiBase: apiBase, nextOperatorRef: operatorRef },
  );
}
