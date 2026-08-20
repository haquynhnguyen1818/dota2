from pydantic import BaseModel


class HeroOut(BaseModel):
    id: int
    name: str
