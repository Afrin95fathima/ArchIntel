import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfidenceMeter, CoverageBar, EvidenceChip, StatusBadge } from './index';
import { Tabs } from './Tabs';

describe('shared evidence presentation primitives', () => {
  it('shows unavailable confidence as unknown instead of zero', () => {
    render(<ConfidenceMeter value={null} />);
    expect(screen.getByText('Not detected')).toBeTruthy();
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBeNull();
  });

  it('shows coverage counts and derives the displayed percentage', () => {
    render(<CoverageBar observed={3} total={4} label="Methods" />);
    expect(screen.getByText('3 / 4')).toBeTruthy();
    expect(screen.getByRole('meter', { name: 'Methods' }).getAttribute('aria-valuenow')).toBe('75');
  });

  it('labels status and evidence in text as well as color', () => {
    render(<><StatusBadge kind="warning">Review needed</StatusBadge><EvidenceChip kind="runtime">Runtime</EvidenceChip></>);
    expect(screen.getByText('Review needed')).toBeTruthy();
    expect(screen.getByText('Runtime')).toBeTruthy();
  });

  it('supports arrow-key movement between workspace tabs', () => {
    const onChange=vi.fn();
    render(<Tabs label="Test tabs" value="one" onChange={onChange} items={[{value:'one',label:'One'},{value:'two',label:'Two'}]}/>);
    fireEvent.keyDown(screen.getByRole('tab',{name:'One'}),{key:'ArrowRight'});
    expect(onChange).toHaveBeenCalledWith('two');
    expect(document.activeElement).toBe(screen.getByRole('tab',{name:'Two'}));
  });
});
