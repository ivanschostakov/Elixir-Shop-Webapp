from pydantic import BaseModel, ConfigDict

class FavouriteBase(BaseModel):
    onec_id: str
    user_id: int

class FavouriteCreate(FavouriteBase): pass
class FavouriteDelete(FavouriteBase): pass

class FavouriteOut(FavouriteBase):
    id: int
    model_config = ConfigDict(from_attributes=True)