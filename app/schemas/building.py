from pydantic import BaseModel, ConfigDict


class BuildingBase(BaseModel):
    name: str
    address: str
    detail_address: str | None = None


class BuildingCreate(BuildingBase):
    invite_code: str


class BuildingRead(BuildingBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
