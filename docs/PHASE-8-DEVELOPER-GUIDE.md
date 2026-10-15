# Phase 8 developer handoff

## Initial slice

`GET /api/v1/architecture-versions/{version_id}/tasks` remains the task-list endpoint. It now adds `blockers`, `validation_state`, `validation_freshness`, and `next_action` to each existing summary. These are derived by the transformation service at read time; no migration or additional durable state was introduced.

`frontend/src/transformation/TaskWorkspace.tsx` renders the summaries in a supervised progress table. The UI only selects an existing task. All mutations remain behind the pre-existing task-specific revision, authorization, and validation workflows.

## Safety and scope

Version ownership is checked before summaries are returned. `next_action` is advisory and based on task state and current gaps. Do not treat it as a policy decision or as proof of eligibility. The endpoint must not trigger jobs or external effects.

Phase 8 remains incomplete. Durable wave/checkpoint state, idempotent orchestration, restart recovery, risk-policy integration, and explicit human start/pause/resume/next-wave controls are not implemented. They depend on validated Phase 7 extraction and data-migration slices, currently parked.

## Validation

The focused transformation test asserts progress summary fields and rejects an unowned/missing architecture version. Run the Phase 8 focused backend test and frontend checks listed in the verification checkpoint before treating this slice as complete.
