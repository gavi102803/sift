from pydantic import BaseModel, ConfigDict


class SiftBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

