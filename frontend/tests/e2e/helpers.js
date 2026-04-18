export async function configureConnection(page, { apiBase = "http://127.0.0.1:8000", operatorRef = "operator" } = {}) {
  await page.evaluate(
    ({ nextApiBase, nextOperatorRef }) => {
      window.localStorage.setItem("novel-system-api-base", nextApiBase);
      window.localStorage.setItem("novel-system-operator-ref", nextOperatorRef);
    },
    { nextApiBase: apiBase, nextOperatorRef: operatorRef },
  );
}
