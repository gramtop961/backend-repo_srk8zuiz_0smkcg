import os
import shutil
import subprocess
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FirmwareIn(BaseModel):
    soc: str = Field(..., description="SoC family: qualcomm | mtk | exynos")
    oem: str = Field(..., description="OEM name, e.g., Google, Samsung, Xiaomi")
    model: str = Field(..., description="Device model, e.g., SM-S921B, Pixel 9 Pro")
    android_version: str = Field(..., description="Android version, e.g., 14 | 15 | 16")
    build_number: Optional[str] = Field(None, description="Firmware build number")
    channel: Optional[str] = Field(None, description="release channel: stable/beta/dev")
    url: Optional[str] = Field(None, description="Official/OEM download URL")
    checksum_sha256: Optional[str] = Field(None, description="SHA256 checksum from OEM")
    notes: Optional[str] = Field(None, description="Additional notes or changelog")


class FirmwareFilter(BaseModel):
    model: Optional[str] = None
    soc: Optional[str] = None
    android_version: Optional[str] = None


class ConsentIn(BaseModel):
    customer_name: str
    device_model: str
    android_version: Optional[str] = None
    operations: List[str] = Field(
        default_factory=list,
        description="Selected operations such as diagnostics, backup, update guidance",
    )
    checklist_confirmed: bool = Field(
        False,
        description="User confirmed battery > 50%, data backup done, OEM firmware only",
    )
    signature: Optional[str] = Field(
        None, description="Typed consent acknowledgement or signature reference"
    )


class WizardRequest(BaseModel):
    soc: str = Field(..., description="qualcomm | mtk | exynos")
    method: str = Field(..., description="fastboot | adb_sideload | odin | oneui_recovery")
    model: Optional[str] = None
    android_version: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        from database import db

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# -----------------------------
# Device diagnostics (safe)
# -----------------------------
@app.get("/api/devices/adb-info")
def adb_info():
    """Return safe ADB environment info if available. Does not change device state."""
    adb_path = shutil.which("adb")
    info = {
        "adb_available": bool(adb_path),
        "adb_path": adb_path,
        "devices": [],
        "errors": [],
    }
    if not adb_path:
        return info

    try:
        out = subprocess.run([adb_path, "devices", "-l"], capture_output=True, text=True, timeout=5)
        info["devices_raw"] = out.stdout
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        for line in lines[1:]:  # skip header
            info["devices"].append(line)
    except Exception as e:
        info["errors"].append(str(e))

    # Best-effort read-only props for Android 14-16
    props = {}
    if not info["devices"]:
        return {**info, "props": props}

    try:
        getprop = subprocess.run([adb_path, "shell", "getprop"], capture_output=True, text=True, timeout=5)
        for key in [
            "ro.product.brand",
            "ro.product.device",
            "ro.product.model",
            "ro.build.id",
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.build.fingerprint",
        ]:
            try:
                gp = subprocess.run(
                    [adb_path, "shell", "getprop", key], capture_output=True, text=True, timeout=5
                )
                props[key] = gp.stdout.strip()
            except Exception:
                props[key] = None
    except Exception as e:
        info["errors"].append(str(e))

    return {**info, "props": props}


# -----------------------------
# Firmware catalog management
# -----------------------------
@app.post("/api/firmware")
def add_firmware(item: FirmwareIn):
    try:
        from database import create_document
        fid = create_document("firmware", item.model_dump())
        return {"id": fid, "status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


@app.post("/api/firmware/search")
def search_firmware(filters: FirmwareFilter):
    try:
        from database import get_documents
        query = {}
        if filters.model:
            query["model"] = filters.model
        if filters.soc:
            query["soc"] = filters.soc
        if filters.android_version:
            query["android_version"] = filters.android_version
        docs = get_documents("firmware", query, limit=100)
        # Convert ObjectId if present
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return {"items": docs}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


# -----------------------------
# Consent and audit logging
# -----------------------------
@app.post("/api/consent")
def record_consent(consent: ConsentIn):
    try:
        from database import create_document
        cid = create_document("consent", consent.model_dump())
        return {"id": cid, "status": "recorded"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


# -----------------------------
# Instruction-only flashing wizard
# -----------------------------
@app.post("/api/wizard/steps")
def wizard_steps(req: WizardRequest):
    soc = (req.soc or "").lower()
    method = (req.method or "").lower()

    if soc not in {"qualcomm", "mtk", "exynos"}:
        raise HTTPException(status_code=400, detail="Unsupported SoC")

    steps: List[str] = []

    if method == "fastboot":
        steps = [
            "Ensure OEM-unlocked bootloader if required by OEM; follow official guidance.",
            "Charge device above 50% and back up user data.",
            "Install official USB drivers and platform-tools.",
            "Reboot device to bootloader/fastboot mode.",
            "Use OEM-provided images matching exact model and Android version (14/15/16).",
            "Validate SHA256 checksum from OEM before proceeding.",
            "Use command-line fastboot to flash ONLY per OEM documentation.",
            "After completion, relock bootloader only if OEM permits and device boots fine.",
        ]
    elif method in {"odin", "oneui_recovery"} and soc == "exynos":
        steps = [
            "Install latest Samsung USB drivers.",
            "Download official firmware from Samsung channels (matching CSC and model).",
            "Start device in Download Mode.",
            "Open Odin on a trusted workstation, load BL/AP/CP/CSC as per OEM instructions.",
            "Verify SHA256 checksums and binary revision (bootloader version).",
            "Start process and wait until pass; do not disconnect.",
            "On success, boot to recovery and wipe cache/data only if recommended by OEM.",
        ]
    elif method == "adb_sideload":
        steps = [
            "Enable USB debugging and OEM unlocking if applicable.",
            "Download official OTA package for your exact model and Android version.",
            "Reboot to recovery and choose 'Apply update from ADB'.",
            "From workstation, run 'adb sideload <ota.zip>' per OEM guidance.",
            "Wait for verification and installation to complete.",
            "Reboot and perform post-update checks.",
        ]
    else:
        raise HTTPException(status_code=400, detail="Unsupported method for selected SoC")

    return {
        "soc": soc,
        "method": method,
        "model": req.model,
        "android_version": req.android_version,
        "steps": steps,
        "disclaimer": "Guidance only. Use official tools and firmware. This app does not execute flashing operations.",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
