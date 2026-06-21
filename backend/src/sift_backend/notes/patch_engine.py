from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from sift_backend.schemas.common import NoteBlockSource
from sift_backend.schemas.concepts import NoteBlockDTO
from sift_backend.schemas.patches import (
    AddRelationPatchOperation,
    AppendPatchOperation,
    PatchOperation,
    ReplacePatchOperation,
)


class PatchErrorCode(StrEnum):
    stale_revision = "staleRevision"
    missing_block = "missingBlock"
    locked_block = "lockedBlock"
    hash_mismatch = "hashMismatch"
    unsupported_operation = "unsupportedOperation"


class PatchApplicationError(ValueError):
    def __init__(self, code: PatchErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NoteSnapshot:
    revision: int
    blocks: tuple[NoteBlockDTO, ...]


@dataclass(frozen=True)
class PatchApplicationResult:
    revision: int
    blocks: tuple[NoteBlockDTO, ...]
    relation_operations: tuple[AddRelationPatchOperation, ...]


def content_hash(content: str) -> str:
    return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"


def apply_patch_operations(
    snapshot: NoteSnapshot,
    base_revision: int,
    operations: list[PatchOperation],
) -> PatchApplicationResult:
    if snapshot.revision != base_revision:
        raise PatchApplicationError(
            PatchErrorCode.stale_revision,
            "Patch was generated against an older note revision.",
        )

    blocks_by_id = {block.id: block for block in snapshot.blocks}
    relation_operations: list[AddRelationPatchOperation] = []

    for operation in operations:
        if isinstance(operation, AppendPatchOperation):
            block = _get_mutable_block(blocks_by_id, operation.target_block_id)
            blocks_by_id[block.id] = block.model_copy(
                update={
                    "content": _append_content(block.content, operation.content),
                    "source": NoteBlockSource.merged,
                    "is_user_locked": block.is_user_locked,
                }
            )
        elif isinstance(operation, ReplacePatchOperation):
            block = _get_mutable_block(blocks_by_id, operation.target_block_id)
            if content_hash(block.content) != operation.old_value_hash:
                raise PatchApplicationError(
                    PatchErrorCode.hash_mismatch,
                    "Patch oldValueHash does not match the current block content.",
                )
            blocks_by_id[block.id] = block.model_copy(
                update={
                    "content": operation.new_content,
                    "source": NoteBlockSource.merged,
                    "is_user_locked": block.is_user_locked,
                }
            )
        elif isinstance(operation, AddRelationPatchOperation):
            relation_operations.append(operation)
        else:
            raise PatchApplicationError(
                PatchErrorCode.unsupported_operation,
                f"Unsupported patch operation: {operation!r}",
            )

    ordered_blocks = tuple(blocks_by_id[block.id] for block in snapshot.blocks)
    return PatchApplicationResult(
        revision=snapshot.revision + 1,
        blocks=ordered_blocks,
        relation_operations=tuple(relation_operations),
    )


def _get_mutable_block(blocks_by_id: dict[UUID, NoteBlockDTO], block_id: UUID) -> NoteBlockDTO:
    block = blocks_by_id.get(block_id)
    if block is None:
        raise PatchApplicationError(
            PatchErrorCode.missing_block,
            "Patch target block does not exist.",
        )
    if block.is_user_locked:
        raise PatchApplicationError(
            PatchErrorCode.locked_block,
            "Patch target block is user locked.",
        )
    return block


def _append_content(existing: str, addition: str) -> str:
    if not existing:
        return addition
    return f"{existing}\n\n{addition}"

