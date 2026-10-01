from pydantic import BaseModel, ConfigDict


class ParkingSlotBase(BaseModel):
    garage_id: int
    number: int
    front_slot_id: int | None = None
    render_x0: float | None = None
    render_y0: float | None = None
    render_x1: float | None = None
    render_y1: float | None = None


class ParkingSlotCreate(ParkingSlotBase):
    pass


class ParkingSlotRead(ParkingSlotBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
