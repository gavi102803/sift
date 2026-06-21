from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel


class AppendPatchOperation(SiftBaseModel):
    operation: Literal["append"]
    target_block_id: UUID = Field(alias="targetBlockId")
    content: str = Field(min_length=1)


class ReplacePatchOperation(SiftBaseModel):
    operation: Literal["replace"]
    target_block_id: UUID = Field(alias="targetBlockId")
    old_value_hash: str = Field(min_length=1, alias="oldValueHash")
    new_content: str = Field(min_length=1, alias="newContent")


class AddRelationPatchOperation(SiftBaseModel):
    operation: Literal["addRelation"]
    target_concept_id: UUID = Field(alias="targetConceptId")
    relation_type: str = Field(min_length=1, alias="relationType")


PatchOperation = Annotated[
    AppendPatchOperation | ReplacePatchOperation | AddRelationPatchOperation,
    Field(discriminator="operation"),
]

