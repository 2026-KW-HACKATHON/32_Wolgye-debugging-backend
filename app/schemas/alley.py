from pydantic import BaseModel, ConfigDict


class AlleyBase(BaseModel):
    name: str
    description: str | None = None


class AlleyCreate(AlleyBase):
    pass


class AlleyRead(AlleyBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
