import React from "react";
import { apiGet } from "./lib/client.js";
import { WsWorks } from "./ws-works.jsx";

const REVIEW_REFRESH_EVENTS = [
  "ws:review-changed",
  "ws:work-changed",
  "ws:trash-changed",
  "ws:snow-saved",
  "ws:catalog-changed",
  "lf:bridge-changed",
];

function useReviewBadge() {
  const [badge, setBadge] = React.useState(null);
  const requestVersion = React.useRef(0);

  React.useEffect(() => {
    let disposed = false;
    let timer = null;

    const refresh = async () => {
      const projectId = WsWorks.activeId();
      const version = ++requestVersion.current;
      if (!projectId || projectId === "__loading__") {
        setBadge(null);
        return;
      }
      try {
        const result = await apiGet(`/api/v1/review-items?state=open&project_id=${encodeURIComponent(projectId)}`);
        if (disposed || version !== requestVersion.current) return;
        const urgent = ((result && result.items) || []).filter((item) => Number(item.priority || 2) === 1).length;
        setBadge(urgent > 0 ? String(urgent) : null);
      } catch (ignored) {
        // 导航徽标是辅助信息；网络失败时保留上次结果，不阻断整个应用外壳。
      }
    };

    const scheduleRefresh = (event) => {
      if (event?.type === "ws:work-changed") setBadge(null);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { void refresh(); }, 180);
    };

    REVIEW_REFRESH_EVENTS.forEach((name) => window.addEventListener(name, scheduleRefresh));
    void refresh();
    return () => {
      disposed = true;
      requestVersion.current += 1;
      window.clearTimeout(timer);
      REVIEW_REFRESH_EVENTS.forEach((name) => window.removeEventListener(name, scheduleRefresh));
    };
  }, []);

  return badge;
}

export { useReviewBadge };
