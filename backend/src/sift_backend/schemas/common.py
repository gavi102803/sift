from enum import StrEnum


class CaptureStatus(StrEnum):
    draft = "draft"
    pending_generation = "pendingGeneration"
    generating = "generating"
    needs_disambiguation = "needsDisambiguation"
    ready = "ready"
    generation_failed = "generationFailed"
    archived = "archived"


class ConceptMaturity(StrEnum):
    initial = "initial"
    growing = "growing"
    mature = "mature"


class NoteBlockType(StrEnum):
    what_it_is = "whatItIs"
    why_it_matters = "whyItMatters"
    example = "example"
    common_misunderstandings = "commonMisunderstandings"
    related_concepts_display = "relatedConceptsDisplay"
    user_takeaways = "userTakeaways"


class NoteBlockSource(StrEnum):
    ai = "ai"
    user = "user"
    merged = "merged"


class UpdateMode(StrEnum):
    none = "none"
    auto_merge = "autoMerge"
    needs_confirmation = "needsConfirmation"


class ProposalStatus(StrEnum):
    proposed = "proposed"
    accepted = "accepted"
    dismissed = "dismissed"
    stale = "stale"


class AnswerSourceType(StrEnum):
    model_knowledge = "modelKnowledge"
    user_provided = "userProvided"
    web_verified = "webVerified"

