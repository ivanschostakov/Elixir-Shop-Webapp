from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud.favourite import add_favourite, remove_favourite
from src.database import get_db
from src.database.schemas import FavouriteCreate, FavouriteDelete, FavouriteOut

router = APIRouter(prefix="/favourites", tags=["favourites"])

class FavouriteDeleteResponse(BaseModel): success: bool

@router.post("", response_model=FavouriteOut, name="favourites_add")
async def favourite_post(favourite_create: FavouriteCreate, db: AsyncSession = Depends(get_db)):
    try: fav = await add_favourite(db, favourite_create)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc))
    return fav

@router.delete("", response_model=FavouriteDeleteResponse, name="favourites_delete")
async def favourite_del(favourite_delete: FavouriteDelete, db: AsyncSession = Depends(get_db)):
    success = await remove_favourite(db, favourite_delete)
    return FavouriteDeleteResponse(success=success)
