"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Class name is converted to lowercase for the collection name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: Optional[str] = Field(None, description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")


class Firmware(BaseModel):
    soc: str = Field(..., description="qualcomm | mtk | exynos")
    oem: str = Field(..., description="OEM name, e.g., Google, Samsung, Xiaomi")
    model: str = Field(..., description="Device model, e.g., SM-S921B, Pixel 9 Pro")
    android_version: str = Field(..., description="Android version: 14 | 15 | 16")
    build_number: Optional[str] = Field(None, description="Build number")
    channel: Optional[str] = Field(None, description="stable | beta | dev")
    url: Optional[str] = Field(None, description="Official/OEM download URL")
    checksum_sha256: Optional[str] = Field(None, description="OEM-provided SHA256 checksum")
    notes: Optional[str] = Field(None, description="Notes / changelog")


class Consent(BaseModel):
    customer_name: str
    device_model: str
    android_version: Optional[str] = None
    operations: List[str] = []
    checklist_confirmed: bool = False
    signature: Optional[str] = None


class Job(BaseModel):
    kind: str = Field(..., description="diagnostic | backup | guidance")
    device_model: Optional[str] = None
    android_version: Optional[str] = None
    status: str = Field("queued", description="queued | in_progress | done | failed")
    notes: Optional[str] = None
