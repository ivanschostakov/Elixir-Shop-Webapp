from typing import Literal

from pydantic import BaseModel


class AvailabilityDestination(BaseModel):
    platform_station_id: str | None = None
    full_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class AvailabilityRequest(BaseModel):
    delivery_mode: Literal["self_pickup", "time_interval"]
    destination: AvailabilityDestination
    send_unix: bool = True
