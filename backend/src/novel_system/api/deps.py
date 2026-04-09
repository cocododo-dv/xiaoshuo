from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from novel_system.db.session import get_db


def get_session(session: Session = Depends(get_db)) -> Session:
    return session
