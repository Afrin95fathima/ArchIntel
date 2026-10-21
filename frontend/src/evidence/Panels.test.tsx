import { cleanup, createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { CoverageMap } from './CoverageMap';
import { DomainBoard } from './DomainBoard';
import { Improvement } from './Improvement';
import { CompareVersions } from './CompareVersions';
import { TargetView } from './TargetView';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={client()}>{ui}</QueryClientProvider>);
const json = (body: unknown, ok = true, status = 200) => ({ ok, status, json: async () => body });

const observations = [
  { id: 'd1', name: 'Owner Visit', observed: 4, total: 8, state: 'PARTIALLY_OBSERVED', unobserved_classes: ['org.x.owner.Owner', 'org.x.owner.Pet'] },
  { id: 'd2', name: 'System Configuration', observed: 4, total: 4, state: 'OBSERVED', unobserved_classes: [] },
];

it('shows each domain against the plan target, how many more classes are needed and which are unobserved', () => {
  render(<CoverageMap observations={observations} target={80} kinds={{ d2: { kind: 'TECHNICAL' } }} hasRuntime />);
  const owner = screen.getByLabelText('Owner Visit coverage');
  expect(within(owner).getByText('4 of 8 classes (50%)')).toBeTruthy();
  expect(within(owner).getByText('3 more classes must be reached to meet the 80% target.')).toBeTruthy();   // ceil(0.8 * 8) = 7, 7 - 4 = 3
  fireEvent.click(within(owner).getByRole('button', { name: 'Show 2 unobserved classes' }));
  expect(within(owner).getByText('owner.Owner')).toBeTruthy();
  const config = screen.getByLabelText('System Configuration coverage');
  expect(within(config).getByText('Meets the 80% target the plan asks for.')).toBeTruthy();
  expect(within(config).getByText(/technical domain: kept as a library, not a service/)).toBeTruthy();
});

it('does not show coverage as reached when no runtime session exists', () => {
  render(<CoverageMap observations={observations} target={80} hasRuntime={false} />);
  expect(screen.getAllByText(/no runtime session/).length).toBe(2);
  expect(screen.queryByText(/Meets the 80% target/)).toBeNull();
});

const board = (extra: Partial<React.ComponentProps<typeof DomainBoard>> = {}) => {
  const onMove = vi.fn(); const onRename = vi.fn();
  render(<DomainBoard domains={[{ id: 'd1', name: 'Vet' }, { id: 'd2', name: 'Config' }]} classes={[{ id: 'org.x.PetClinicApplication', domain_id: 'd1' }, { id: 'org.x.vet.Vet', domain_id: 'd1' }]} names={{}} membership={{}} onMove={onMove} onRename={onRename} {...extra} />);
  return { onMove, onRename };
};

it('moves a class by dropping it on another domain and also through its menu', () => {
  const { onMove } = board();
  const chip = screen.getByTitle('org.x.PetClinicApplication').closest('li') as HTMLElement;
  const data: Record<string, string> = {};
  const dragStart = createEvent.dragStart(chip); Object.defineProperty(dragStart, 'dataTransfer', { value: { setData: (k: string, v: string) => { data[k] = v; }, effectAllowed: '' } });
  fireEvent(chip, dragStart);
  const target = screen.getByLabelText('Domain Config');
  const drop = createEvent.drop(target); Object.defineProperty(drop, 'dataTransfer', { value: { getData: (k: string) => data[k] } });
  fireEvent(target, drop);
  expect(onMove).toHaveBeenCalledWith('org.x.PetClinicApplication', 'd2');
  fireEvent.change(screen.getByLabelText('Domain for org.x.vet.Vet'), { target: { value: 'd2' } });
  expect(onMove).toHaveBeenLastCalledWith('org.x.vet.Vet', 'd2');
});

it('shows moved classes, size changes and an empty domain warning, and renames a domain', () => {
  const { onRename } = board({ membership: { 'org.x.PetClinicApplication': 'd2' } });
  expect(within(screen.getByLabelText('Domain Vet')).getByText('1 class (was 2)')).toBeTruthy();
  expect(within(screen.getByLabelText('Domain Config')).getByText('1 class (was 0)')).toBeTruthy();
  cleanup();
  board({ membership: { 'org.x.PetClinicApplication': 'd2', 'org.x.vet.Vet': 'd2' } });
  expect(within(screen.getByLabelText('Domain Vet')).getByRole('alert').textContent).toBe('A domain cannot be empty.');
  cleanup();
  const again = board();
  fireEvent.change(screen.getByLabelText('Name for d1'), { target: { value: 'Veterinary' } });
  expect(again.onRename).toHaveBeenCalledWith('d1', 'Veterinary');
  expect(onRename).not.toHaveBeenCalled();
});

it('filters the board by class name', () => {
  board();
  fireEvent.change(screen.getByLabelText('Find a class'), { target: { value: 'petclinicapp' } });
  expect(screen.queryByTitle('org.x.vet.Vet')).toBeNull();
  expect(screen.getByTitle('org.x.PetClinicApplication')).toBeTruthy();
});

const improvement = { target_percentage: 80, ready: false,
  conditions: [{ id: 'RUNTIME_SESSION', met: true, text: 'A completed runtime session is part of this version.' }, { id: 'DOMAIN_REVIEW', met: false, text: 'The domain boundaries were not reviewed for this version.' }],
  domains: [{ id: 'd1', name: 'Owner Visit', observed: 4, total: 8, percentage: 50, target_percentage: 80, met: false, classes_needed: 3, unobserved_classes: [], reachable_by_open_suggestions: 4, can_reach_target: true },
            { id: 'd2', name: 'Vet', observed: 2, total: 10, percentage: 20, target_percentage: 80, met: false, classes_needed: 6, unobserved_classes: [], reachable_by_open_suggestions: 0, can_reach_target: false }],
  suggestions: [{ discovery_id: 'g1', text: 't', entry_class: 'org.x.owner.PetController', method: 'processUpdateForm', domain_name: 'Owner Visit', up_to_new_classes: 4, reachable_unobserved: [], per_domain: { 'Owner Visit': 4 } }],
  limits: ['The gain of a suggestion is an upper bound.'] };

it('lists what the plan still asks for and the best flows, labelling gains as upper bounds', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(improvement)));
  wrap(<Improvement versionId="v1" />);
  const panel = await screen.findByLabelText('What would improve this plan');
  expect(within(panel).getByText(/2 of 2 domains are below the target/)).toBeTruthy();
  expect(within(panel).getByText(/Not met: The domain boundaries were not reviewed/)).toBeTruthy();
  expect(within(panel).getByText('up to 4')).toBeTruthy();
  expect(within(panel).getByText('No: needs other flows')).toBeTruthy();
  expect(within(panel).getByText(/PetController\.processUpdateForm/)).toBeTruthy();
  expect(within(panel).getByText(/up to 4 more classes \(Owner Visit 4\)/)).toBeTruthy();
  expect(within(panel).getByText(/upper bound/)).toBeTruthy();
});

it('says so when the improvement estimate cannot be loaded', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'x' }, false, 500)));
  wrap(<Improvement versionId="v1" />);
  expect(await screen.findByRole('alert')).toBeTruthy();
});

const comparison = { from_version: 'v0', to_version: 'v1', same_domain_review: false, percentage_point_delta: { classes: 48, domains: null },
  runtime_sessions: { before: 0, after: 2 }, domains: [{ id: 'd1', name: 'Owner Visit', before: { observed: 0, total: 8 }, after: { observed: 4, total: 8 } }],
  moved_classes: [{ cls: 'org.x.PetClinicApplication', from_domain: 'Vet', to_domain: 'System Configuration' }], moved_total: 3, renamed_domains: [{ id: 'd1', from_name: 'Type', to_name: 'Pet Types' }],
  facts: { before: { STATIC_AND_DYNAMIC: 0, STATIC_ONLY: 40, DYNAMIC_ONLY: 0 }, after: { STATIC_AND_DYNAMIC: 6, STATIC_ONLY: 34, DYNAMIC_ONLY: 25 }, changed: [{ source: 'org.x.owner.VisitController', target: 'org.x.owner.OwnerRepository', before: 'STATIC_ONLY', after: 'STATIC_AND_DYNAMIC' }], changed_total: 31 },
  suggestions: { before: 48, after: 29, closed: ['Exercise org.x.A.b and capture method identity evidence.'], closed_total: 19, opened: [], opened_total: 0 } };

it('compares the selected version with an earlier one in plain sections', async () => {
  const fetchMock = vi.fn(async (_url: string) => json(comparison)); vi.stubGlobal('fetch', fetchMock);
  wrap(<CompareVersions current={{ id: 'v1', name: 'Now', analysis_id: 'a' }} versions={[{ id: 'v1', name: 'Now', analysis_id: 'a' }, { id: 'v0', name: 'Before', analysis_id: 'a' }, { id: 'vx', name: 'Other baseline', analysis_id: 'b' }]} />);
  const select = screen.getByLabelText('Earlier version') as HTMLSelectElement;
  expect([...select.options].map(o => o.textContent)).toEqual(['Select a version', 'Before (v0)']);        // same baseline only, never itself
  fireEvent.change(select, { target: { value: 'v0' } });
  expect(await screen.findByText(/0 before, 2 now\./)).toBeTruthy();
  expect(fetchMock.mock.calls[0][0]).toContain('/architecture-versions/v0/compare/v1');
  expect(screen.getByText('Owner Visit: 0 of 8 classes before, 4 of 8 now (+4)')).toBeTruthy();
  expect(screen.getByText(/Classes \+48 points/)).toBeTruthy();
  expect(screen.getByText(/The domain delta is withheld because the two versions use different domain boundaries/)).toBeTruthy();
  expect(screen.getByText('Renamed: Type to Pet Types')).toBeTruthy();
  expect(screen.getByText('Moved x.PetClinicApplication from Vet to System Configuration')).toBeTruthy();
  expect(screen.getByText('2 more classes moved.')).toBeTruthy();
  expect(screen.getByText('owner.VisitController → owner.OwnerRepository: In code only before, Confirmed by code and runtime now')).toBeTruthy();
  expect(screen.getByText('19 closed and 0 new (48 before, 29 now).')).toBeTruthy();
});

it('explains why nothing can be compared when only one version exists', () => {
  render(<CompareVersions current={{ id: 'v1', name: 'Now', analysis_id: 'a' }} versions={[{ id: 'v1', name: 'Now', analysis_id: 'a' }]} />);
  expect(screen.getByText(/nothing to compare yet/)).toBeTruthy();
});

it('puts the proposed services next to the current domains and flags a technical domain', async () => {
  const candidate = (id: string, name: string, state: string) => ({ id, name, repository_name: name.toLowerCase(), proposal_state: state, class_ids: ['a', 'b'], dependencies: id === 'd1' ? ['d2'] : [], consumers: [], decision: 'COLLECT_MORE_EVIDENCE', readiness: 70, blockers: ['RUNTIME_OBSERVATION_GAP'] });
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/modernization')
    ? json([{ id: 'p1', strategy: 'MICROSERVICES', objective: 'o' }])
    : json({ id: 'p1', document: { microservice_decomposition: { status: 'PROPOSAL_ONLY', service_candidates: [candidate('d1', 'Vet', 'CANDIDATE_REQUIRES_REVIEW'), candidate('d2', 'System Configuration', 'TECHNICAL_DOMAIN_NOT_A_SERVICE')] } }, reviews: [{ state: 'APPROVED_PLANNING' }, { state: 'REJECTED' }] })));
  wrap(<TargetView versionId="v1" domains={[{ id: 'd1', name: 'Vet', classes: [] }, { id: 'd2', name: 'System Configuration', classes: [] }]} />);
  expect(await screen.findByText('Candidate service, needs business review')).toBeTruthy();
  expect(screen.getByText('Not a service: keep as shared configuration or a library')).toBeTruthy();
  expect(screen.getByText('Latest review: rejected.')).toBeTruthy();                       // the latest review, not the earlier approval
  expect(screen.getAllByText('1 blocker').length).toBe(2);
  expect(screen.getByText(/This is a proposal only; no code was generated or changed/)).toBeTruthy();
});

it('says when the version has no saved plan', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json([])));
  wrap(<TargetView versionId="v1" domains={[]} />);
  expect(await screen.findByText(/No modernization plan has been saved for this version/)).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
