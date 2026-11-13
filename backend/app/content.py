"""Published snapshots are separate from drafts; public reads never serialize drafts."""
import hmac
from contextlib import contextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .api_support import Owner, Limit, Offset, collection, output
from .config import settings
from .db import ContentSection, Session, transaction

router = APIRouter(prefix="/api")


@contextmanager
def content_session(write=False):
    try:
        with (transaction() if write else Session()) as session:
            yield session
    except SQLAlchemyError:
        raise HTTPException(503, "Website content is temporarily unavailable") from None


class ContentData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field("", max_length=300)
    description: str = Field("", max_length=10000)
    image: str = Field("", max_length=2048)
    image_alt: str = Field("", max_length=300)
    link: str = Field("", max_length=2048)
    button: str = Field("", max_length=100)
    canonical: str = Field("", max_length=2048)

    @field_validator("image", "link", "canonical")
    @classmethod
    def safe_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if (any(ord(c) < 33 for c in value) or "\\" in value or
                parsed.username or parsed.password or
                not (value.startswith("/") and not value.startswith("//") or
                     parsed.scheme == "https" and parsed.hostname)):
            raise ValueError("Use a local absolute path or HTTPS URL without credentials")
        return value


class ContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["draft", "published", "archived"] = "draft"
    position: int = Field(0, ge=0, le=10000)
    draft: ContentData


async def administrator(owner: Owner, authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ")
    if not any(hmac.compare_digest(token, key.strip()) for key in settings().content_admin_keys.split(",") if key.strip()):
        raise HTTPException(403, "Content administrator access required")
    return owner


Admin = Annotated[str, Depends(administrator)]


@router.get("/content")
def public_content():
    with content_session() as session:
        rows = session.scalars(select(ContentSection).where(
            ContentSection.status != "archived", ContentSection.published.is_not(None)
        ).order_by(ContentSection.position, ContentSection.key))
        return {"items": [{"key": r.key, "position": r.position, **r.published} for r in rows]}


@router.get("/admin/content")
def list_content(admin: Admin, offset: Offset = 0, limit: Limit = 100):
    with content_session() as session:
        return collection(session, select(ContentSection).order_by(ContentSection.position, ContentSection.key), offset, limit)


@router.post("/admin/content/{key}")
def save_content(key: str, data: ContentInput, admin: Admin):
    import re
    if not re.fullmatch(r"[A-Za-z0-9 _-]{1,80}", key):
        raise HTTPException(422, "Invalid section key")
    with content_session(write=True) as session:
        item = session.get(ContentSection, key)
        if item is None:
            item = ContentSection(key=key)
            session.add(item)
        item.draft = data.draft.model_dump()
        item.position = data.position
        item.status = data.status
        if data.status == "published":
            item.published = item.draft.copy()
        session.flush()
        return output(item)


@router.delete("/admin/content/{key}", status_code=204)
def delete_content(key: str, admin: Admin):
    with content_session(write=True) as session:
        item = session.get(ContentSection, key)
        if not item:
            raise HTTPException(404, "Section not found")
        session.delete(item)
