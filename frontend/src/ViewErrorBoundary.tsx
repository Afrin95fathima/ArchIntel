import { Component, type ReactNode } from 'react';

/** A render failure in one screen must not blank the whole application: it shows the reason and resets when another screen opens. */
export class ViewErrorBoundary extends Component<{ view: string; children: ReactNode }, { error: Error | null; view: string }> {
  state = { error: null as Error | null, view: this.props.view };
  static getDerivedStateFromError(error: Error) { return { error }; }
  static getDerivedStateFromProps(props: { view: string }, state: { error: Error | null; view: string }) { return props.view !== state.view ? { error: null, view: props.view } : null; }
  componentDidCatch(error: Error) { console.error('ArchIntel screen failed to render:', error); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="error-box" role="alert"><strong>This screen could not be displayed.</strong> {this.state.error.message}. The saved analysis and plan are unchanged. Open another screen or reload the page; the failure is recorded in the browser console.</div>;
  }
}
