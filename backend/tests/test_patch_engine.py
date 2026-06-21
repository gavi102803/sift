from uuid import uuid4

import pytest

from sift_backend.notes.patch_engine import (
    NoteSnapshot,
    PatchApplicationError,
    PatchErrorCode,
    apply_patch_operations,
    content_hash,
)
from sift_backend.schemas.common import NoteBlockSource, NoteBlockType
from sift_backend.schemas.concepts import NoteBlockDTO
from sift_backend.schemas.patches import (
    AddRelationPatchOperation,
    AppendPatchOperation,
    ReplacePatchOperation,
)


def make_block(content: str = "Original", is_user_locked: bool = False) -> NoteBlockDTO:
    return NoteBlockDTO(
        id=uuid4(),
        blockType=NoteBlockType.what_it_is,
        content=content,
        source=NoteBlockSource.ai,
        isUserLocked=is_user_locked,
    )


def test_append_patch_adds_content_and_increments_revision() -> None:
    block = make_block("RAG retrieves external context.")
    snapshot = NoteSnapshot(revision=1, blocks=(block,))

    result = apply_patch_operations(
        snapshot,
        base_revision=1,
        operations=[
            AppendPatchOperation(
                operation="append",
                targetBlockId=block.id,
                content="It then uses that context during generation.",
            )
        ],
    )

    assert result.revision == 2
    assert "external context" in result.blocks[0].content
    assert "during generation" in result.blocks[0].content
    assert result.blocks[0].source == NoteBlockSource.merged


def test_replace_patch_requires_matching_old_value_hash() -> None:
    block = make_block("Old definition")
    snapshot = NoteSnapshot(revision=1, blocks=(block,))

    result = apply_patch_operations(
        snapshot,
        base_revision=1,
        operations=[
            ReplacePatchOperation(
                operation="replace",
                targetBlockId=block.id,
                oldValueHash=content_hash("Old definition"),
                newContent="New definition",
            )
        ],
    )

    assert result.blocks[0].content == "New definition"


def test_replace_patch_rejects_hash_mismatch() -> None:
    block = make_block("Current definition")
    snapshot = NoteSnapshot(revision=1, blocks=(block,))

    with pytest.raises(PatchApplicationError) as error:
        apply_patch_operations(
            snapshot,
            base_revision=1,
            operations=[
                ReplacePatchOperation(
                    operation="replace",
                    targetBlockId=block.id,
                    oldValueHash=content_hash("Outdated definition"),
                    newContent="New definition",
                )
            ],
        )

    assert error.value.code == PatchErrorCode.hash_mismatch


def test_patch_rejects_stale_base_revision() -> None:
    block = make_block()
    snapshot = NoteSnapshot(revision=2, blocks=(block,))

    with pytest.raises(PatchApplicationError) as error:
        apply_patch_operations(
            snapshot,
            base_revision=1,
            operations=[
                AppendPatchOperation(
                    operation="append",
                    targetBlockId=block.id,
                    content="Extra context",
                )
            ],
        )

    assert error.value.code == PatchErrorCode.stale_revision


def test_patch_rejects_user_locked_block() -> None:
    block = make_block(is_user_locked=True)
    snapshot = NoteSnapshot(revision=1, blocks=(block,))

    with pytest.raises(PatchApplicationError) as error:
        apply_patch_operations(
            snapshot,
            base_revision=1,
            operations=[
                AppendPatchOperation(
                    operation="append",
                    targetBlockId=block.id,
                    content="Extra context",
                )
            ],
        )

    assert error.value.code == PatchErrorCode.locked_block


def test_add_relation_patch_is_collected_without_mutating_blocks() -> None:
    block = make_block()
    target_concept_id = uuid4()
    snapshot = NoteSnapshot(revision=1, blocks=(block,))

    result = apply_patch_operations(
        snapshot,
        base_revision=1,
        operations=[
            AddRelationPatchOperation(
                operation="addRelation",
                targetConceptId=target_concept_id,
                relationType="related",
            )
        ],
    )

    assert result.revision == 2
    assert result.blocks[0].content == block.content
    assert result.relation_operations[0].target_concept_id == target_concept_id

