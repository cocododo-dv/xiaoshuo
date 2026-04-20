async (page) => {
  await page.getByTestId('nav-workbench').click();
  await page.getByTestId('scene-workbench-view').waitFor({ timeout: 30000 });
  const results = [];
  for (const sceneId of ['CHQA01_SC01', 'CHQA02_SC01', 'CHQA03_SC01']) {
    await page.getByTestId('scene-id-input').fill(sceneId);
    await page.getByTestId('scene-load-button').click();
    await page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 30000 }).catch(() => null);
    const [response] = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/run/full`) && resp.request().method() === 'POST', { timeout: 900000 }),
      page.getByTestId('run-full-scene-button').click(),
    ]);
    const payload = await response.json();
    await page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 60000 }).catch(() => null);
    const statusResponse = await page.request.get(`http://127.0.0.1:8000/api/v1/scenes/${sceneId}/status`);
    const statusPayload = await statusResponse.json();
    results.push({ sceneId, httpStatus: response.status(), payload, status: statusPayload });
  }
  return results;
}
