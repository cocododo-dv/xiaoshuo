async (page) => {
  const loopback = 'http://127.0.0.1';
  const apiBase =
    (typeof process !== 'undefined' && process.env?.PLAYWRIGHT_API_BASE) ||
    `${loopback}:${(typeof process !== 'undefined' && process.env?.PLAYWRIGHT_BACKEND_PORT) || '8000'}`;
  const headers = { 'X-Operator-Ref': 'qa.three-chapters.real-llm', 'X-Idempotency-Key': `qa-chqa03-mark-last-${Date.now()}` };
  await page.request.post(`${apiBase}/api/v1/chapters/CHQA03/scene-order`, {
    headers,
    data: { scene_ids: ['CHQA03_SC01'], last_scene_id: 'CHQA03_SC01' },
  });
  await page.getByTestId('nav-workbench').click();
  await page.getByTestId('scene-workbench-view').waitFor({ timeout: 30000 });
  await page.getByTestId('scene-id-input').fill('CHQA03_SC01');
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes('/api/v1/scenes/CHQA03_SC01/workbench'), { timeout: 30000 }).catch(() => null),
    page.getByTestId('scene-load-button').click(),
  ]);
  await page.getByTestId('chapter-manual-hold-reason-input').fill('QA smoke hold before final aggregate');
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes('/api/v1/chapters/CHQA03/runtime/manual-hold') && resp.request().method() === 'POST', { timeout: 30000 }),
    page.getByTestId('chapter-manual-hold-set-button').click(),
  ]);
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes('/api/v1/chapters/CHQA03/runtime/manual-hold/clear') && resp.request().method() === 'POST', { timeout: 30000 }),
    page.getByTestId('chapter-manual-hold-clear-button').click(),
  ]);
  const [aggregateResponse] = await Promise.all([
    page.waitForResponse((resp) => resp.url().includes('/api/v1/chapters/CHQA03/runtime/aggregate/final') && resp.request().method() === 'POST', { timeout: 30000 }),
    page.getByTestId('chapter-final-aggregate-button').click(),
  ]);
  const aggregatePayload = await aggregateResponse.json();
  const chapterStatus = await (await page.request.get(`${apiBase}/api/v1/chapters/CHQA03/status`, { headers: { 'X-Operator-Ref': 'qa.three-chapters.real-llm' } })).json();
  return { aggregatePayload, chapterStatus };
}
