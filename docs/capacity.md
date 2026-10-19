# ArcIntel capacity record

Fill a row only from a recorded ramp test on the named environment. Blank cells mean unmeasured; they are not zero and do not imply support.

| Version | Hardware | Max classes tested | Max edges tested | Max input MB tested | Scan time | Peak RAM | Single scan or modular merge | Outcome / limit exhausted |
|---|---|---:|---:|---:|---:|---:|---|---|
|  |  |  |  |  |  |  |  |  |

Current benchmark tooling measures synthetic in-process analysis only. It does not measure upload, extraction, jQAssistant/Neo4j, persistence, concurrent scans, or runtime telemetry. Do not treat those figures as service capacity.

Limit defaults in `backend/app/config.py` marked “unvalidated, to be set from ramp-test results” are placeholders. Validate them on deployment hardware using representative real artifacts before raising them or publishing capacity numbers.
