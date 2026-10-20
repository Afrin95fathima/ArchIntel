import { useEffect, useState } from 'react';

/** What the user is looking at, published by pages and read by the docked assistant. */
export type AssistantSelection = { kind: 'class' | 'package' | 'domain' | 'session'; id: string; label: string };
const EVENT = 'archintel-assistant-context';

export function publishAssistantContext(selection: AssistantSelection | null) {
  window.dispatchEvent(new CustomEvent<AssistantSelection | null>(EVENT, { detail: selection }));
}

export function useAssistantSelection(): AssistantSelection | null {
  const [selection, setSelection] = useState<AssistantSelection | null>(null);
  useEffect(() => {
    const on = (event: Event) => setSelection((event as CustomEvent<AssistantSelection | null>).detail);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return selection;
}

const OPEN = 'archintel-open-assistant';
/** Any page can ask the dock to open, for example from a "Ask about this architecture" link. */
export function openAssistant() { window.dispatchEvent(new Event(OPEN)); }
export function onOpenAssistant(handler: () => void) { window.addEventListener(OPEN, handler); return () => window.removeEventListener(OPEN, handler); }
