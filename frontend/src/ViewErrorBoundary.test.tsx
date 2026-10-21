import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ViewErrorBoundary, isStaleBuild, reloadOnce } from './ViewErrorBoundary';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function Broken({ message }: { message: string }): never { throw new Error(message); }

it('shows the reason and keeps the rest of the page when a screen throws while rendering', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<><nav>Sidebar stays</nav><ViewErrorBoundary view="planning"><Broken message="Cannot read properties of undefined (reading 'join')" /></ViewErrorBoundary></>);
  expect(screen.getByText('Sidebar stays')).toBeTruthy();
  expect(screen.getByRole('alert').textContent).toContain("This screen could not be displayed.");
  expect(screen.getByRole('alert').textContent).toContain("Cannot read properties of undefined (reading 'join')");
  expect(screen.getByRole('alert').textContent).toContain('The saved analysis and plan are unchanged');
});

it('shows the next screen normally once another view is opened', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const { rerender } = render(<ViewErrorBoundary view="planning"><Broken message="boom" /></ViewErrorBoundary>);
  expect(screen.getByRole('alert')).toBeTruthy();
  rerender(<ViewErrorBoundary view="overview"><p>Overview content</p></ViewErrorBoundary>);
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByText('Overview content')).toBeTruthy();
});

it('renders its children untouched when nothing fails', () => {
  render(<ViewErrorBoundary view="overview"><p>All good</p></ViewErrorBoundary>);
  expect(screen.getByText('All good')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});


it('recognises the error a browser raises when a script from an older build no longer exists', () => {
  expect(isStaleBuild(new Error('Failed to fetch dynamically imported module: http://x/assets/Hub-1.js'))).toBe(true);
  expect(isStaleBuild(new Error('error loading dynamically imported module'))).toBe(true);
  expect(isStaleBuild(new Error("Cannot read properties of undefined (reading 'join')"))).toBe(false);
});

it('reloads once per session so a server that is really down cannot cause a reload loop', () => {
  sessionStorage.clear();
  const reload = vi.fn();
  expect(reloadOnce(reload)).toBe(true);
  expect(reloadOnce(reload)).toBe(false);
  expect(reload).toHaveBeenCalledTimes(1);
});

it('reloads a stale page automatically but still shows the message if the reload does not help', () => {
  sessionStorage.clear();
  const reload = vi.fn();
  vi.stubGlobal('location', { ...window.location, reload });
  vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<ViewErrorBoundary view="planning"><Broken message="Failed to fetch dynamically imported module: http://x/assets/Hub-1.js" /></ViewErrorBoundary>);
  expect(reload).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem('archintel-stale-reload')).toBe('1');
  expect(screen.getByRole('alert').textContent).toContain('Failed to fetch dynamically imported module');
});
