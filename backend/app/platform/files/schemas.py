"""Files API models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

#: purposes a client may upload (exports and generated documents are created by services only)
UploadPurpose = Literal["image", "document", "import"]


class FileRead(BaseModel):
    id: uuid.UUID
    sha256: str
    size_bytes: int
    kind: str
    content_type: str
    original_name: str
    purpose: str
    restricted: bool
    created_at: datetime
    #: true when identical bytes were already stored for the company (the existing file is returned)
    deduplicated: bool = False
    #: same-origin, cookie-authenticated download link (never a token in the query string)
    content_url: str
