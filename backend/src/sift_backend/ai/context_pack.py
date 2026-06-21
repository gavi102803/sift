from dataclasses import dataclass
from typing import Any

from sift_backend.ai.litellm_client import LiteLLMMessage
from sift_backend.schemas.concepts import ConceptDTO


@dataclass(frozen=True)
class RecentTurn:
    role: str
    content: str


@dataclass(frozen=True)
class ContextPack:
    messages: tuple[LiteLLMMessage, ...]
    response_format: dict[str, Any]


def build_concept_turn_context_pack(
    concept: ConceptDTO,
    card_memory: str,
    recent_turns: list[RecentTurn],
    user_query: str,
) -> ContextPack:
    system_prompt = "\n".join(
        [
            "You are Sift's learning-note assistant for one concept card.",
            (
                "Answer the user's current question, then decide whether the durable "
                "note should change."
            ),
            "Never overwrite user-locked note blocks.",
            "Use patch operations for note changes; do not describe note edits in prose only.",
            "If a change touches the core definition or a user-edited block, require confirmation.",
        ]
    )

    context_payload = {
        "concept": {
            "id": str(concept.id),
            "canonicalTitle": concept.canonical_title,
            "displayTitle": concept.display_title,
            "maturity": concept.maturity,
            "captureStatus": concept.capture_status,
            "noteRevision": concept.note_revision,
        },
        "currentNote": [
            {
                "id": str(block.id),
                "blockType": block.block_type,
                "content": block.content,
                "source": block.source,
                "isUserLocked": block.is_user_locked,
            }
            for block in concept.blocks
        ],
        "cardMemory": card_memory,
    }

    messages = [
        LiteLLMMessage(role="system", content=system_prompt),
        LiteLLMMessage(role="system", content=f"Context pack:\n{context_payload}"),
    ]
    messages.extend(
        LiteLLMMessage(role=turn.role, content=turn.content)
        for turn in recent_turns[-10:]
        if turn.role in {"user", "assistant"}
    )
    messages.append(LiteLLMMessage(role="user", content=user_query))

    return ContextPack(
        messages=tuple(messages),
        response_format=concept_turn_response_format(),
    )


def concept_turn_response_format() -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "answer",
            "answerSource",
            "updateDecision",
            "relations",
            "suggestedTags",
            "suggestedTopics",
            "memoryPatch",
            "modelMeta",
        ],
        "properties": {
            "answer": {"type": "string"},
            "answerSource": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sourceType", "confidence"],
                "properties": {
                    "sourceType": {
                        "type": "string",
                        "enum": ["modelKnowledge", "userProvided", "webVerified"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "uncertaintyNote": {"type": ["string", "null"]},
                },
            },
            "updateDecision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "reason"],
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["none", "autoMerge", "needsConfirmation"],
                    },
                    "reason": {"type": "string"},
                },
            },
            "autoPatch": {
                "type": "array",
                "items": patch_operation_schema(),
            },
            "proposal": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["baseNoteRevision", "patchOperations", "rationale"],
                        "properties": {
                            "baseNoteRevision": {"type": "integer", "minimum": 0},
                            "patchOperations": {
                                "type": "array",
                                "items": patch_operation_schema(),
                            },
                            "rationale": {"type": "string"},
                        },
                    },
                ]
            },
            "relations": {"type": "array", "items": {"type": "object"}},
            "suggestedTags": {"type": "array", "items": tag_or_topic_schema()},
            "suggestedTopics": {"type": "array", "items": tag_or_topic_schema()},
            "memoryPatch": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "confirmedUnderstanding": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "openQuestions": {"type": "array", "items": {"type": "string"}},
                    "userPreferences": {"type": "array", "items": {"type": "string"}},
                },
            },
            "modelMeta": {
                "type": "object",
                "additionalProperties": False,
                "required": ["provider", "model"],
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "latencyMs": {"type": ["integer", "null"], "minimum": 0},
                    "inputTokens": {"type": ["integer", "null"], "minimum": 0},
                    "outputTokens": {"type": ["integer", "null"], "minimum": 0},
                },
            },
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "concept_turn_result",
            "strict": True,
            "schema": schema,
        },
    }


def patch_operation_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "targetBlockId", "content"],
                "properties": {
                    "operation": {"const": "append"},
                    "targetBlockId": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "targetBlockId", "oldValueHash", "newContent"],
                "properties": {
                    "operation": {"const": "replace"},
                    "targetBlockId": {"type": "string"},
                    "oldValueHash": {"type": "string"},
                    "newContent": {"type": "string"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "targetConceptId", "relationType"],
                "properties": {
                    "operation": {"const": "addRelation"},
                    "targetConceptId": {"type": "string"},
                    "relationType": {"type": "string"},
                },
            },
        ]
    }


def tag_or_topic_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "confidence"],
        "properties": {
            "name": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
