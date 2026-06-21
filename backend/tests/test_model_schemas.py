from uuid import uuid4

import pytest
from pydantic import ValidationError

from sift_backend.schemas.common import AnswerSourceType, UpdateMode
from sift_backend.schemas.model_outputs import ConceptTurnResult
from sift_backend.schemas.patches import AppendPatchOperation, ReplacePatchOperation


def test_concept_turn_result_accepts_valid_structured_output() -> None:
    block_id = uuid4()
    payload = {
        "answer": "RAG retrieves context before generating an answer.",
        "answerSource": {
            "sourceType": AnswerSourceType.model_knowledge,
            "confidence": 0.72,
        },
        "updateDecision": {
            "mode": UpdateMode.auto_merge,
            "reason": "Adds a safe example.",
        },
        "autoPatch": [
            {
                "operation": "append",
                "targetBlockId": str(block_id),
                "content": "Enterprise search is a common RAG use case.",
            }
        ],
        "relations": [],
        "suggestedTags": [{"name": "AI", "confidence": 0.9}],
        "suggestedTopics": [{"name": "AI Systems", "confidence": 0.8}],
        "memoryPatch": {
            "confirmedUnderstanding": ["RAG uses retrieved context."],
            "openQuestions": [],
            "userPreferences": ["Use practical examples."],
        },
        "modelMeta": {
            "provider": "openai",
            "model": "sift-explain",
            "latencyMs": 820,
            "inputTokens": 400,
            "outputTokens": 120,
        },
    }

    result = ConceptTurnResult.model_validate(payload)

    assert result.update_mode == UpdateMode.auto_merge
    assert isinstance(result.auto_patch[0], AppendPatchOperation)
    assert result.auto_patch[0].target_block_id == block_id


def test_patch_operation_requires_discriminator_specific_fields() -> None:
    payload = {
        "answer": "A risky definition change.",
        "answerSource": {
            "sourceType": AnswerSourceType.model_knowledge,
            "confidence": 0.6,
        },
        "updateDecision": {
            "mode": UpdateMode.needs_confirmation,
            "reason": "Changes the definition.",
        },
        "proposal": {
            "baseNoteRevision": 1,
            "patchOperations": [
                {
                    "operation": "replace",
                    "targetBlockId": str(uuid4()),
                    "newContent": "A revised definition without old hash.",
                }
            ],
            "rationale": "The existing definition is too vague.",
        },
        "modelMeta": {"provider": "anthropic", "model": "sift-curate"},
    }

    with pytest.raises(ValidationError):
        ConceptTurnResult.model_validate(payload)


def test_replace_patch_accepts_hash_guard() -> None:
    operation = ReplacePatchOperation.model_validate(
        {
            "operation": "replace",
            "targetBlockId": str(uuid4()),
            "oldValueHash": "sha256:abc",
            "newContent": "Updated content",
        }
    )

    assert operation.old_value_hash == "sha256:abc"

