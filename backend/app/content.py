"""Published snapshots are separate from drafts; public reads never serialize drafts."""
import hmac
import time
import uuid
from contextlib import contextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update, delete
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from .api_support import Owner, Limit, Offset, collection, output
from .config import settings
from .db import ContentSection, Session, transaction

router = APIRouter(prefix="/api")


@contextmanager
def content_session(write=False):
    try:
        with (transaction() if write else Session()) as session:
            yield session
    except IntegrityError:
        raise HTTPException(409, "Section changed; reload before saving") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Website content is temporarily unavailable") from None


class ContentData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    navigation_label: str = Field("", max_length=80)
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
    revision: str | None = Field(None, pattern=r"^[0-9a-f-]{36}$")
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


@router.get("/admin/content/{key}")
def get_content(key: str, admin: Admin):
    with content_session() as session:
        item=session.get(ContentSection,key)
        if item is None:
            raise HTTPException(404,"Section not found")
        return output(item)


@router.post("/admin/content/{key}")
def save_content(key: str, data: ContentInput, admin: Admin):
    import re
    if not re.fullmatch(r"[A-Za-z0-9 _-]{1,80}", key):
        raise HTTPException(422, "Invalid section key")
    if data.revision is None:
        with content_session() as session:
            if session.get(ContentSection,key) is not None:
                raise HTTPException(428, "Load the current section and provide its revision")
    with content_session(write=True) as session:
        if data.revision is None:
            item = ContentSection(key=key, draft=data.draft.model_dump(), status=data.status, position=data.position)
            if data.status=='published':
                item.published=data.draft.model_dump()
            session.add(item)
            session.flush()
            return output(item)
        values = dict(draft=data.draft.model_dump(),status=data.status,position=data.position,
                      revision=str(uuid.uuid4()),updated_at=time.time())
        if data.status=='published':
            values['published']=data.draft.model_dump()
        result=session.execute(update(ContentSection).where(ContentSection.key==key,ContentSection.revision==data.revision).values(**values))
        if result.rowcount!=1:
            raise HTTPException(409, "Section changed; your draft was not saved. Reload and merge before saving")
        session.expire_all()
        return output(session.get(ContentSection,key))


@router.delete("/admin/content/{key}", status_code=204)
def delete_content(key: str, admin: Admin, if_match: Annotated[str | None, Header()] = None):
    with content_session(write=True) as session:
        if if_match is None:
            raise HTTPException(428, "Provide the loaded revision in If-Match")
        revision=if_match.strip('"')
        result=session.execute(delete(ContentSection).where(ContentSection.key==key,ContentSection.revision==revision))
        if result.rowcount!=1:
            if session.get(ContentSection,key) is None:
                raise HTTPException(404,"Section not found")
            raise HTTPException(409, "Section changed; reload before deleting")
