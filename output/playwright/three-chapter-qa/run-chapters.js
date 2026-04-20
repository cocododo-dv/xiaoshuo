async (page) => {
  const results = [];
  for (const chapterId of ['CHQA01', 'CHQA02', 'CHQA03']) {
    await page.getByTestId(`author-chapter-select-${chapterId}`).click();
    await page.getByTestId('author-run-chapter-button').click();
    const panel = page.getByTestId('chapter-run-status-panel');
    await panel.waitFor({ timeout: 10000 });
    await page.waitForFunction(
      (id) => {
        const panel = document.querySelector('[data-testid="chapter-run-status-panel"]');
        const text = panel ? panel.textContent || '' : '';
        return text.includes(id) && /(completed|blocked|failed|error)/i.test(text);
      },
      chapterId,
      { timeout: 300000 }
    ).catch(() => null);
    results.push({ chapterId, panel: await panel.textContent() });
  }
  return results;
}
