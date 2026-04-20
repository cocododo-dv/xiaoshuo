async (page) => {
const chapters = [
  {
    id: 'CHQA02',
    goal: '第二章：沈澜和程砚在旧城门追查潮汐码，发现导师曾经隐瞒一场码头事故。',
    plot: '把潮汐码、旧城门守夜人、码头事故连成一条可追踪线。',
    emotion: '从互不信任转向被共同危险逼出短暂协作。',
    ending: '守夜人留下半枚铜钥匙，指向废弃码头的地下库。',
    notes: 'QA 三章真实 LLM 闭环 - 第二章。',
    scene: {
      id: 'CHQA02_SC01',
      pov: 'CHAR_SHENLAN',
      goal: '沈澜和程砚在旧城门夜查潮汐码，守夜人用半真半假的证词把他们引向码头事故。',
      chars: '沈澜，程砚，守夜人',
      location: '旧城门雨夜岗亭',
      beats: '核对潮汐码，询问守夜人，发现铜钥匙，遭遇停电',
      include: '铜钥匙沾着黑色盐渍，城门钟声停在十一点',
      forbidden: '梦醒，系统提示，作者原文复制',
      exit: '二人决定连夜去废弃码头',
      hook: '岗亭墙内传来导师录音',
      length: 'short',
      type: 'investigation'
    }
  },
  {
    id: 'CHQA03',
    goal: '第三章：废弃码头地下库揭开导师失踪的真正动机，沈澜必须决定是否公开证据。',
    plot: '让三章线索在地下库汇合，并留下下一卷的硬视觉钩子。',
    emotion: '从追索真相转向承担真相带来的代价。',
    ending: '沈澜拿到证据时，海面升起一艘本该沉没的旧船。',
    notes: 'QA 三章真实 LLM 闭环 - 第三章。',
    scene: {
      id: 'CHQA03_SC01',
      pov: 'CHAR_SHENLAN',
      goal: '沈澜在废弃码头地下库找到导师藏起的证据，明白来信是在保护另一个幸存者。',
      chars: '沈澜，程砚，神秘幸存者',
      location: '废弃码头地下库',
      beats: '打开铜锁，找到录音，辨认幸存者，海面出现旧船',
      include: '地下库墙上有潮汐刻痕，旧船无灯却逆潮靠岸',
      forbidden: '梦醒，系统提示，作者原文复制',
      exit: '沈澜决定先保护幸存者再公开证据',
      hook: '旧船甲板上站着导师的身影',
      length: 'short',
      type: 'reveal'
    }
  }
];
async function fillByTestId(id, value) {
  const el = page.getByTestId(id);
  await el.fill(value);
}
for (const chapter of chapters) {
  await page.getByTestId('author-new-chapter-button').click();
  await fillByTestId('author-chapter-id', chapter.id);
  await fillByTestId('author-chapter-scene-count', '1');
  await fillByTestId('author-chapter-goal', chapter.goal);
  await page.getByRole('textbox', { name: '主线推进' }).fill(chapter.plot);
  await page.getByRole('textbox', { name: '情绪目标' }).fill(chapter.emotion);
  await page.getByRole('textbox', { name: '结尾效果' }).fill(chapter.ending);
  await page.getByRole('textbox', { name: '禁止包含' }).fill('不要梦醒、不要旁白解释全部真相、不要直接复制参考书句子。');
  await page.getByRole('textbox', { name: '备注' }).fill(chapter.notes);
  await page.getByTestId('author-save-chapter-button').click();
  await page.getByText(`已保存章节 ${chapter.id}`).first().waitFor({ timeout: 10000 });
  await fillByTestId('author-scene-id', chapter.scene.id);
  await page.getByRole('textbox', { name: '视角角色' }).fill(chapter.scene.pov);
  await fillByTestId('author-scene-goal', chapter.scene.goal);
  await page.getByRole('textbox', { name: '出场角色' }).fill(chapter.scene.chars);
  await page.getByRole('textbox', { name: '地点' }).fill(chapter.scene.location);
  await page.getByRole('textbox', { name: '节拍' }).fill(chapter.scene.beats);
  await page.getByRole('textbox', { name: '必须包含' }).fill(chapter.scene.include);
  await page.getByRole('textbox', { name: '禁用文本' }).fill(chapter.scene.forbidden);
  await page.getByRole('textbox', { name: '离场变化' }).fill(chapter.scene.exit);
  await page.getByRole('textbox', { name: '钩子' }).fill(chapter.scene.hook);
  await page.getByRole('textbox', { name: '目标篇幅档位' }).fill(chapter.scene.length);
  await page.getByRole('textbox', { name: '场景类型' }).fill(chapter.scene.type);
  await page.getByTestId('author-save-scene-button').click();
  await page.getByText(`已保存场景 ${chapter.scene.id}`).first().waitFor({ timeout: 10000 });
}

}
