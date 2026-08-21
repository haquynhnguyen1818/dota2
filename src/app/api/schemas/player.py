from pydantic import BaseModel


class PlayerOut(BaseModel):
    account_id: int
    name: str
