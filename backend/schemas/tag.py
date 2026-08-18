from pydantic import BaseModel

from enums import TagCategory


class TagOut(BaseModel):
    id: int
    name: str
    category: TagCategory
    model_config = {"from_attributes": True}
