from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    plate_no: str
    color: str | None = None
    nickname: str | None = None
    is_primary: bool = False


class VehicleCreate(VehicleBase):
    owner_id: int | None = None


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int | None = None
