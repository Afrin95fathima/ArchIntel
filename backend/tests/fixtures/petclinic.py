"""Labelled Spring PetClinic fixture for domain-discovery evaluation.

Classes are grouped into three ground-truth labels:
  * "clinic"   - owner / pet / visit domain (org.springframework.samples.petclinic.owner.*)
  * "vet"      - vet domain (org.springframework.samples.petclinic.vet.*)
  * "system"   - application/bootstrap/domain (PetClinicApplication + web.*)

Spring Boot loader / autoconfigure classes are present in ``classes`` but are
excluded by default scoping (they carry no label and must not appear in a
discovered domain).
"""
from app.services.graph import build_graphs

PACKAGE = 'org.springframework.samples.petclinic'

_CLASSES = [
    # --- clinic: owner / pet / visit -------------------------------------
    (PACKAGE + '.owner.Owner', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.owner.Pet', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.owner.Visit', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.owner.PetType', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.owner.OwnerRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.owner.PetRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.owner.VisitRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.owner.PetTypeRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.owner.OwnerService',
     dict(annotations=['org.springframework.stereotype.Service'])),
    (PACKAGE + '.owner.PetService',
     dict(annotations=['org.springframework.stereotype.Service'])),
    (PACKAGE + '.owner.VisitService',
     dict(annotations=['org.springframework.stereotype.Service'])),
    (PACKAGE + '.owner.OwnerController',
     dict(annotations=['org.springframework.stereotype.Controller'])),
    (PACKAGE + '.owner.PetController',
     dict(annotations=['org.springframework.stereotype.Controller'])),
    (PACKAGE + '.owner.VisitController',
     dict(annotations=['org.springframework.stereotype.Controller'])),
    # --- vet --------------------------------------------------------------
    (PACKAGE + '.vet.Vet', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.vet.Specialty', dict(annotations=['jakarta.persistence.Entity'])),
    (PACKAGE + '.vet.VetRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.vet.SpecialtyRepository',
     dict(annotations=['org.springframework.stereotype.Repository'])),
    (PACKAGE + '.vet.VetService',
     dict(annotations=['org.springframework.stereotype.Service'])),
    (PACKAGE + '.vet.VetController',
     dict(annotations=['org.springframework.stereotype.Controller'])),
    # --- system -----------------------------------------------------------
    (PACKAGE + '.PetClinicApplication',
     dict(annotations=['org.springframework.boot.autoconfigure.SpringBootApplication'])),
    (PACKAGE + '.web.ExceptionHandler',
     dict(annotations=['org.springframework.web.bind.annotation.ControllerAdvice'])),
    (PACKAGE + '.web.WebConfig',
     dict(annotations=['org.springframework.context.annotation.Configuration'])),
    (PACKAGE + '.web.SystemService',
     dict(annotations=['org.springframework.stereotype.Service'])),
    # --- framework loader (excluded, not labelled) ------------------------
    ('org.springframework.boot.loader.Launcher', dict(annotations=[])),
    ('org.springframework.boot.loader.archive.Archive', dict(annotations=[])),
    ('org.springframework.boot.autoconfigure.SpringBootApplicationInitializer',
     dict(annotations=[])),
]

# Ground-truth labels: class fqn -> domain label.
LABELS = {
    PACKAGE + '.owner.Owner': 'clinic',
    PACKAGE + '.owner.Pet': 'clinic',
    PACKAGE + '.owner.Visit': 'clinic',
    PACKAGE + '.owner.PetType': 'clinic',
    PACKAGE + '.owner.OwnerRepository': 'clinic',
    PACKAGE + '.owner.PetRepository': 'clinic',
    PACKAGE + '.owner.VisitRepository': 'clinic',
    PACKAGE + '.owner.PetTypeRepository': 'clinic',
    PACKAGE + '.owner.OwnerService': 'clinic',
    PACKAGE + '.owner.PetService': 'clinic',
    PACKAGE + '.owner.VisitService': 'clinic',
    PACKAGE + '.owner.OwnerController': 'clinic',
    PACKAGE + '.owner.PetController': 'clinic',
    PACKAGE + '.owner.VisitController': 'clinic',
    PACKAGE + '.vet.Vet': 'vet',
    PACKAGE + '.vet.Specialty': 'vet',
    PACKAGE + '.vet.VetRepository': 'vet',
    PACKAGE + '.vet.SpecialtyRepository': 'vet',
    PACKAGE + '.vet.VetService': 'vet',
    PACKAGE + '.vet.VetController': 'vet',
    PACKAGE + '.PetClinicApplication': 'system',
    PACKAGE + '.web.ExceptionHandler': 'system',
    PACKAGE + '.web.WebConfig': 'system',
    PACKAGE + '.web.SystemService': 'system',
}

# Directed static edges: dependent -> dependency.
_EDGES = [
    # clinic: controllers -> services -> repositories -> entities
    (PACKAGE + '.owner.OwnerController', PACKAGE + '.owner.OwnerService'),
    (PACKAGE + '.owner.PetController', PACKAGE + '.owner.PetService'),
    (PACKAGE + '.owner.PetController', PACKAGE + '.owner.OwnerService'),
    (PACKAGE + '.owner.VisitController', PACKAGE + '.owner.VisitService'),
    (PACKAGE + '.owner.VisitController', PACKAGE + '.owner.PetService'),
    (PACKAGE + '.owner.OwnerService', PACKAGE + '.owner.OwnerRepository'),
    (PACKAGE + '.owner.OwnerService', PACKAGE + '.owner.Owner'),
    (PACKAGE + '.owner.PetService', PACKAGE + '.owner.PetRepository'),
    (PACKAGE + '.owner.PetService', PACKAGE + '.owner.Pet'),
    (PACKAGE + '.owner.PetService', PACKAGE + '.owner.OwnerRepository'),
    (PACKAGE + '.owner.VisitService', PACKAGE + '.owner.VisitRepository'),
    (PACKAGE + '.owner.VisitService', PACKAGE + '.owner.Visit'),
    (PACKAGE + '.owner.VisitService', PACKAGE + '.owner.PetRepository'),
    (PACKAGE + '.owner.OwnerRepository', PACKAGE + '.owner.Owner'),
    (PACKAGE + '.owner.PetRepository', PACKAGE + '.owner.Pet'),
    (PACKAGE + '.owner.VisitRepository', PACKAGE + '.owner.Visit'),
    (PACKAGE + '.owner.PetTypeRepository', PACKAGE + '.owner.PetType'),
    # clinic cross-links binding owner / pet / visit into one cohesive domain
    (PACKAGE + '.owner.VisitService', PACKAGE + '.owner.OwnerService'),
    (PACKAGE + '.owner.PetService', PACKAGE + '.owner.OwnerService'),
    (PACKAGE + '.owner.VisitController', PACKAGE + '.owner.OwnerService'),
    (PACKAGE + '.owner.OwnerService', PACKAGE + '.owner.Visit'),
    (PACKAGE + '.owner.OwnerService', PACKAGE + '.owner.Pet'),
    (PACKAGE + '.owner.OwnerService', PACKAGE + '.owner.PetType'),
    (PACKAGE + '.owner.PetService', PACKAGE + '.owner.VisitService'),
    (PACKAGE + '.owner.OwnerController', PACKAGE + '.owner.VisitController'),
    # vet
    (PACKAGE + '.vet.VetController', PACKAGE + '.vet.VetService'),
    (PACKAGE + '.vet.VetService', PACKAGE + '.vet.VetRepository'),
    (PACKAGE + '.vet.VetService', PACKAGE + '.vet.Vet'),
    (PACKAGE + '.vet.VetService', PACKAGE + '.vet.SpecialtyRepository'),
    (PACKAGE + '.vet.VetRepository', PACKAGE + '.vet.Vet'),
    (PACKAGE + '.vet.SpecialtyRepository', PACKAGE + '.vet.Specialty'),
    # system: web layer -> SystemService; application root anchors the group
    (PACKAGE + '.web.ExceptionHandler', PACKAGE + '.web.SystemService'),
    (PACKAGE + '.web.WebConfig', PACKAGE + '.web.SystemService'),
    (PACKAGE + '.PetClinicApplication', PACKAGE + '.web.SystemService'),
    # framework loader edges (excluded)
    ('org.springframework.boot.loader.Launcher', PACKAGE + '.PetClinicApplication'),
    ('org.springframework.boot.autoconfigure.SpringBootApplicationInitializer',
     PACKAGE + '.PetClinicApplication'),
]


def build():
    """Return (classes, edges, labels) ready for ``discover_domains``."""
    classes_list = [dict(fqn=f, simple_name=f.rsplit('.', 1)[-1],
                         package_name=f.rpartition('.')[0] or '(default)',
                         annotations=a.get('annotations', [])) for f, a in _CLASSES]
    classes = {c['fqn']: c for c in classes_list}
    edges = [dict(source=s, target=t, dependency_type='METHOD_CALL') for s, t in _EDGES]
    return classes, edges, dict(LABELS)


def graph():
    classes, edges, _ = build()
    return build_graphs(list(classes.values()), edges, [])
