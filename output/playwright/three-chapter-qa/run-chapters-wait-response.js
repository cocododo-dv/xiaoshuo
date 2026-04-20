async (page) => {
  await page.reload();
  await page.getByTestId('nav-author').click();
  await page.getByTestId('author-workspace-view').waitFor({ timeout: 30000 });
  const results = [];
  for (const chapterId of ['CHQA01', 'CHQA02', 'CHQA03']) {
    await page.getByTestId(`author-chapter-select-${chapterId}`).click();
    await page.getByTestId('author-run-chapter-button').waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="author-run-chapter-button"]');
      return button && !button.disabled;
    }, null, { timeout: 30000 });
    const [response] = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/chapters/${chapterId}/run/full`) && resp.request().method() === 'POST', { timeout: 420000 }),
      page.getByTestId('author-run-chapter-button').click(),
    ]);
    const payload = await response.json();
    await page.getByTestId(`author-chapter-select-${chapterId}`).click();
    const statusResponse = await page.request.get(`http://127.0.0.1:8000/api/v1/chapters/${chapterId}/run-status`);
    const statusPayload = await statusResponse.json();
    results.push({ chapterId, httpStatus: response.status(), payload, status: statusPayload });
  }
  return results;
}

