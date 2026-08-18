import React from "react";
import { TweakRadio, TweakSection, TweakSlider, TweakToggle } from "./tweaks-panel.jsx";

const WRITER_TWEAK_DEFAULTS = {
  measure: 680,
  fontSize: 18,
  lineHeight: 2.05,
  focus: "light",
  ambient: true,
  aiPlace: "tray",
  wrLayout: "desk",
  typewriter: false,
};

function WriterTweaks({ t, setTweak }) {
  const tw = { ...WRITER_TWEAK_DEFAULTS, ...(t || {}) };
  return (
    <>
      <TweakSection label="工作台布局" />
      <TweakRadio label="布局" value={tw.wrLayout === "immersive" ? "immersive" : "desk"}
        options={[{ value: "desk", label: "书桌三栏" }, { value: "immersive", label: "沉浸稿纸" }]}
        onChange={(value) => setTweak("wrLayout", value)} />
      <TweakSection label="专注与协作" />
      <TweakRadio label="柔和专注（暗化旁段）" value={tw.focus}
        options={[{ value: "off", label: "关" }, { value: "light", label: "轻" }, { value: "medium", label: "中" }, { value: "deep", label: "深" }]}
        onChange={(value) => setTweak("focus", value)} />
      <TweakToggle label="当前行氛围光" value={tw.ambient} onChange={(value) => setTweak("ambient", value)} />
      <TweakToggle label="打字机滚动（当前行居中）" value={tw.typewriter} onChange={(value) => setTweak("typewriter", value)} />
      <TweakRadio label="AI 候选呈现位置" value={tw.aiPlace}
        options={[{ value: "tray", label: "底部托盘" }, { value: "drawer", label: "右侧抽屉" }]}
        onChange={(value) => setTweak("aiPlace", value)} />

      <TweakSection label="稿纸排版" />
      <TweakSlider label="稿纸宽度" value={tw.measure} min={560} max={860} step={20} unit="px" onChange={(value) => setTweak("measure", value)} />
      <TweakSlider label="正文字号" value={tw.fontSize} min={15} max={24} unit="px" onChange={(value) => setTweak("fontSize", value)} />
      <TweakSlider label="行距" value={tw.lineHeight} min={1.5} max={2.6} step={0.05} onChange={(value) => setTweak("lineHeight", value)} />
    </>
  );
}

function SceneTweaks({ t, setTweak }) {
  return (
    <>
      <TweakSection label="AI 起草台" />
      <TweakSlider label="正文字号" value={t.scnFont ?? 16} min={15} max={20} step={1} unit="px"
        onChange={(value) => setTweak("scnFont", value)} />
      <TweakRadio label="证据栏密度" value={t.scnDensity ?? "cozy"}
        options={[{ value: "cozy", label: "疏朗" }, { value: "compact", label: "紧凑" }]}
        onChange={(value) => setTweak("scnDensity", value)} />
      <TweakToggle label="戏剧卡边条" value={t.scnBeats !== false}
        onChange={(value) => setTweak("scnBeats", value)} />
      <TweakToggle label="运行日志默认展开" value={t.scnLog !== false}
        onChange={(value) => setTweak("scnLog", value)} />
      <TweakSection label="质检阈值 · 对已生成稿实时重算" />
      <TweakSlider label="短句率目标" value={t.scnShort ?? 55} min={30} max={85} step={5} unit="%"
        onChange={(value) => setTweak("scnShort", value)} />
      <TweakSlider label="句式重复上限" value={t.scnRepeat ?? 30} min={10} max={60} step={5} unit="%"
        onChange={(value) => setTweak("scnRepeat", value)} />
      <TweakSlider label="超长句阈值" value={t.scnLong ?? 64} min={40} max={120} step={4} unit="字"
        onChange={(value) => setTweak("scnLong", value)} />
    </>
  );
}

export { SceneTweaks, WriterTweaks, WRITER_TWEAK_DEFAULTS };
