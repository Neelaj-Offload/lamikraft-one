from app.platform.events.catalogue import event_defs
from app.platform.events.handler_job import handle_event
from app.platform.jobs.defs import JobDef
from app.platform.manifest import ModuleManifest

MANIFEST = ModuleManifest(
    name="events",
    models=("app.platform.events.models",),
    events=event_defs(),
    jobs=[JobDef(kind="event.handle", handler=handle_event, queue="events", max_attempts=8)],
)
