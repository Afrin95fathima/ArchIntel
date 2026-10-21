"""Background execution and step bookkeeping shared by exploration and conversion jobs."""
import threading
import traceback
from app.models import now
from .models import AutomationJob

LOCK = threading.Lock()
ACTIVE: set[str] = set()


def view(job: AutomationJob) -> dict:
    return dict(id=job.id, application_id=job.application_id, analysis_id=job.analysis_id, kind=job.kind, state=job.state,
                created_at=job.created_at, updated_at=job.updated_at, **job.document)


class Steps:
    """Records each step in the job document as it starts, finishes or fails, committing every change."""

    def __init__(self, sessions, job_id: str):
        self.sessions, self.job_id = sessions, job_id

    def update(self, **changes):
        with self.sessions() as db:
            job = db.get(AutomationJob, self.job_id)
            document = dict(job.document)
            for key, value in changes.items():
                if key == 'state':
                    job.state = value
                else:
                    document[key] = value
            job.document, job.updated_at = document, now()
            db.commit()

    def step(self, name: str, state: str, detail: str | None = None, **data):
        with self.sessions() as db:
            job = db.get(AutomationJob, self.job_id)
            document = dict(job.document)
            steps = [s for s in document.get('steps', []) if s['name'] != name]
            previous = next((s for s in document.get('steps', []) if s['name'] == name), {})
            steps.append(dict(previous, name=name, state=state, detail=detail, at=now().isoformat(), **data))
            document['steps'] = steps
            job.document, job.updated_at = document, now()
            db.commit()


def spawn(job_id: str, target, *args):
    """Run one job in a daemon thread; a job id is never run twice at the same time."""
    with LOCK:
        if job_id in ACTIVE:
            return False
        ACTIVE.add(job_id)

    def body():
        try:
            target(*args)
        except Exception:                                   # the job function records its own failure; this is a last resort
            traceback.print_exc()
        finally:
            with LOCK:
                ACTIVE.discard(job_id)
    threading.Thread(target=body, name=f'automation-{job_id[:8]}', daemon=True).start()
    return True
