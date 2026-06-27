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
    seed = "seed"
    growing = "growing"
    mature = "mature"
    needs_review = "needsReview"


class NoteBlockType(StrEnum):
    one_line_definition = "oneLineDefinition"
    what_it_is = "whatItIs"
    why_it_matters = "whyItMatters"
    example = "example"
    distinction = "distinction"
    misconception = "misconception"
    user_context = "userContext"
    open_question = "openQuestion"
    related_concepts = "relatedConcepts"
    caveat = "caveat"
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
    search_discovered = "searchDiscovered"
    source_verified = "sourceVerified"
    web_verified = "webVerified"


class SourceType(StrEnum):
    official = "official"
    primary = "primary"
    secondary = "secondary"
    user_provided = "userProvided"


class ClaimType(StrEnum):
    definition = "definition"
    distinction = "distinction"
    fact = "fact"


class EvidenceStatus(StrEnum):
    model_explanation = "modelExplanation"
    source_backed = "sourceBacked"
    user_note = "userNote"


class TimeSensitivity(StrEnum):
    stable = "stable"
    time_sensitive = "timeSensitive"


class LearningStateField(StrEnum):
    user_context = "userContext"
    confirmed_understanding = "confirmedUnderstanding"
    open_questions = "openQuestions"
    recurring_confusions = "recurringConfusions"


class LearningStateOrigin(StrEnum):
    user_explicit = "userExplicit"
    user_confirmed = "userConfirmed"
    assistant_inference = "assistantInference"


class CandidateUpdateOperation(StrEnum):
    append_block = "appendBlock"
    add_open_question = "addOpenQuestion"
    add_relation = "addRelation"
    add_claim = "addClaim"
    replace_block = "replaceBlock"
    replace_claim = "replaceClaim"


class ProposalReason(StrEnum):
    core_definition_change = "coreDefinitionChange"
    protected_user_content = "protectedUserContent"
    conflicting_evidence = "conflictingEvidence"
    time_sensitive_fact = "timeSensitiveFact"
    structural_change = "structuralChange"
