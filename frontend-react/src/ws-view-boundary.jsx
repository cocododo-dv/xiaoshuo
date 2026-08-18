import React from "react";

function ViewLoading({ label = "页面" }) {
  return (
    <section className="ws-view-loading" role="status" aria-live="polite">
      <span className="ws-view-loading-mark" aria-hidden="true" />
      <strong>正在打开{label}…</strong>
      <span>首次进入时需要加载这一模块。</span>
    </section>
  );
}

function ProjectRequired({ label = "这个页面", onCreate, onGoHome }) {
  return (
    <section className="ws-project-required" role="status" data-testid="project-required">
      <span className="ws-project-required-kicker">WORKSPACE REQUIRED</span>
      <h2>先创建一部作品</h2>
      <p>「{label}」里的内容必须归属于明确作品，系统不会把数据写进匿名或加载占位空间。</p>
      <div className="ws-project-required-actions">
        <button type="button" className="btn btn-accent" onClick={onCreate}>创建第一部作品</button>
        <button type="button" className="btn btn-ghost" onClick={onGoHome}>回到主页</button>
      </div>
    </section>
  );
}

class ViewErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.retry = this.retry.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    try {
      window.dispatchEvent(new CustomEvent("ws:view-error", {
        detail: {
          message: error instanceof Error ? error.message : String(error || "未知错误"),
          componentStack: info?.componentStack || "",
          view: this.props.resetKey || "unknown",
        },
      }));
    } catch (ignored) {
      // 错误隔离层本身不能因为遥测不可用而再次崩溃。
    }
  }

  componentDidUpdate(previousProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  retry() {
    this.setState({ error: null });
    this.props.onRetry?.();
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="ws-view-error" role="alert" data-testid="view-error-boundary">
        <span className="ws-view-error-kicker">MODULE RECOVERY</span>
        <h2>这个页面没有正常打开</h2>
        <p>故障已被限制在当前模块，其他工作台仍可继续使用。可以先重试；如果是资源加载失败，重新加载应用会重新获取文件。</p>
        <div className="ws-view-error-actions">
          <button type="button" className="btn btn-accent" onClick={this.retry}>重试当前页面</button>
          <button type="button" className="btn btn-ghost" onClick={this.props.onGoHome}>回到主页</button>
          <button type="button" className="btn btn-quiet" onClick={() => window.location.reload()}>重新加载应用</button>
        </div>
      </section>
    );
  }
}

export { ProjectRequired, ViewErrorBoundary, ViewLoading };
