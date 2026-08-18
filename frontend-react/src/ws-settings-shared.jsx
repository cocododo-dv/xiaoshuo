import React from "react";


const SET_PREFS_LS = "ws_prefs_v1";

function setPrefsLoad() {
  try { return JSON.parse(localStorage.getItem(SET_PREFS_LS)) || {}; } catch (e) { return {}; }
}

function usePref(key, defaultValue) {
  const [value, setValue] = React.useState(() => {
    const all = setPrefsLoad();
    return all[key] !== undefined ? all[key] : defaultValue;
  });
  const set = (nextValue) => {
    setValue(nextValue);
    try {
      const all = setPrefsLoad();
      all[key] = nextValue;
      localStorage.setItem(SET_PREFS_LS, JSON.stringify(all));
    } catch (e) {}
  };
  return [value, set];
}

function Section({ title, desc, children }) {
  return (
    <section className="set-section">
      <header className="set-section-head">
        <h2 className="set-section-title text-serif">{title}</h2>
        {desc && <p className="set-section-desc">{desc}</p>}
      </header>
      <div className="set-section-body">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="set-row">
      <div>
        <div className="set-row-label">{label}</div>
        {hint && <div className="set-row-hint">{hint}</div>}
      </div>
      <div className="set-row-ctl">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange }) {
  return (
    <button type="button" className={`toggle ${on ? "is-on" : ""}`} onClick={() => onChange(!on)} aria-label="切换">
      <span className="toggle-knob" />
    </button>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="seg">
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          className={`seg-btn ${value === option.value ? "is-active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export { Section, Row, Toggle, Segmented, usePref };
