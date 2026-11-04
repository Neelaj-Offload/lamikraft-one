"""Placeholder replaced below."""

from fastapi import APIRouter

router = APIRouter(prefix="/migration", tags=["migration"])
backups_router = APIRouter(prefix="/system/backups", tags=["system"])
