async (page) => {
  await page.getByTestId('nav-knowledge').click();
  await page.getByTestId('knowledge-console-view').waitFor({ timeout: 20000 });
  const candidates = [
    {
      reviewId: 'review_qa_voice_shenlan',
      itemType: 'voice_card_candidate',
      lineageKey: 'VOICE_CHAR_SHENLAN',
      text: '沈澜的声线冷静、克制、观察细节优先。她在压力下会先描述物件触感，再短句追问，不使用夸张抒情。',
      chapterId: 'CHQA01',
      sceneId: 'CHQA01_SC01',
      characterId: 'CHAR_SHENLAN',
      objectType: 'voice_card',
    },
    {
      reviewId: 'review_qa_relation_shenlan_chengyan',
      itemType: 'relation_card_candidate',
      lineageKey: 'REL_沈澜_程砚',
      text: '沈澜与程砚互相保留旧案信息，互动以试探、打断和共同校验证据推进；关系张力来自互不完全信任但必须协作。',
      chapterId: 'CHQA01',
      sceneId: 'CHQA01_SC01',
      leftCharacterId: '沈澜',
      rightCharacterId: '程砚',
      objectType: 'relation_card',
    },
    {
      reviewId: 'review_qa_style_rule_three_chapters',
      itemType: 'style_rule_set',
      lineageKey: 'STYLE_QA_THREE_CHAPTERS',
      text: '保持动作和物件驱动的悬疑感；每场至少有一个可触摸细节，一个未说出口的关系压力点，一个硬视觉钩子。',
      chapterId: 'CHQA01',
      sceneId: 'CHQA01_SC01',
      objectType: 'style_rule',
    },
    {
      reviewId: 'review_qa_calibration_three_chapters',
      itemType: 'calibration_candidate',
      lineageKey: 'CAL_QA_THREE_CHAPTERS',
      text: '信纸擦过她指腹，盐粒先碎开，疑问才慢半拍抵达喉咙。',
      chapterId: 'CHQA01',
      sceneId: 'CHQA01_SC01',
      objectType: 'calibration_line',
      activeOnApprove: '0',
    },
  ];
  const created = [];
  for (const item of candidates) {
    await page.getByTestId('knowledge-review-id').fill(item.reviewId);
    await page.getByTestId('knowledge-item-type').selectOption(item.itemType);
    await page.getByTestId('knowledge-lineage-key').fill(item.lineageKey);
    await page.getByTestId('knowledge-candidate-text').fill(item.text);
    await page.getByTestId('knowledge-active-on-approve').selectOption(item.activeOnApprove || '1');
    await page.locator('input').filter({ hasText: '' }).count();
    await page.getByLabel('章节 ID').fill(item.chapterId);
    await page.getByLabel('场景 ID').fill(item.sceneId);
    const character = page.getByLabel('角色 ID');
    if (await character.count()) await character.fill(item.characterId || '');
    const left = page.getByLabel('左角色');
    if (await left.count()) await left.fill(item.leftCharacterId || '');
    const right = page.getByLabel('右角色');
    if (await right.count()) await right.fill(item.rightCharacterId || '');
    await page.getByTestId('knowledge-create-button').click();
    await page.getByText(item.reviewId).first().waitFor({ timeout: 15000 }).catch(() => null);
    await page.getByTestId(`knowledge-view-detail-${item.objectType}-${item.lineageKey}`).click();
    await page.getByTestId(`knowledge-approve-review-${item.reviewId}`).click();
    await page.getByText(`已批准 ${item.reviewId}`).first().waitFor({ timeout: 15000 });
    if (item.activeOnApprove === '0') {
      await page.getByTestId(`knowledge-retry-verify-verify_${item.reviewId}`).click();
      await page.getByText(`已重试校验 verify_${item.reviewId}`).first().waitFor({ timeout: 15000 });
      await page.getByTestId(`knowledge-release-review-${item.reviewId}`).click();
      await page.getByText(`已发布 ${item.reviewId}`).first().waitFor({ timeout: 15000 });
    }
    created.push(item.reviewId);
  }
  return created;
}
