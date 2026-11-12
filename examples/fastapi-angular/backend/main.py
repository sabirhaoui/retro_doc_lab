"""Synthetic example: this file is parsed, never imported or executed."""
from fastapi import FastAPI, APIRouter, HTTPException

app = FastAPI()
router = APIRouter(prefix='/items')


@router.get('/{item_id}')
def read_item(item_id: int):
    if item_id < 1:
        raise HTTPException(status_code=404, detail='Missing item')
    return {'id': item_id}


app.include_router(router, prefix='/api')
