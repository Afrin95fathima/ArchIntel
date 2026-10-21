import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ViewErrorBoundary } from './ViewErrorBoundary';

afterEach(cleanup);
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
