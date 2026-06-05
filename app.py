import asyncio
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = BASE_DIR / "captured_photos"
TEMPLATE_DIR = BASE_DIR / "templates"
CAPTURE_TIMEOUT_SECONDS = int(os.getenv("PHOTOBOOTH_CAPTURE_TIMEOUT", "45"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".arw", ".heic", ".tif", ".tiff"}

CAPTURE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Sony α7 IV Web Photobooth")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app.mount("/captured_photos", StaticFiles(directory=str(CAPTURE_DIR)), name="captured_photos")

MACOS_CAMERA_HELPERS = ("ptpcamerad", "mscamerad-xpc", "icdd")


class CameraError(RuntimeError):
    """Raised when a camera capture cannot complete safely."""


def _safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


def _target_path(source_name: str) -> Path:
    timestamp_ms = int(time.time() * 1000)
    unique_id = uuid.uuid4().hex
    return CAPTURE_DIR / f"{timestamp_ms}-{unique_id}{_safe_extension(source_name)}"


def _latest_image(directory: Path) -> Path:
    candidates = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    if not candidates:
        raise CameraError("No image file was returned by the camera.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _capture_with_gphoto2_cli() -> Path:
    binary = os.getenv("GPHOTO2_BIN") or "gphoto2"
    executable = shutil.which(binary) if not Path(binary).is_file() else binary
    if not executable:
        raise CameraError("gphoto2.exe was not found. Install gphoto2 and/or set GPHOTO2_BIN.")

    with tempfile.TemporaryDirectory(prefix="photobooth-capture-") as temp_dir:
        temp_path = Path(temp_dir)
        try:
            result = subprocess.run(
                [executable, "--capture-image-and-download", "--force-overwrite"],
                cwd=temp_path,
                text=True,
                capture_output=True,
                timeout=CAPTURE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CameraError("Timed out while waiting for the camera to capture.") from exc
        except OSError as exc:
            raise CameraError(f"Unable to start gphoto2: {exc}") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Unknown gphoto2 failure").strip()
            raise CameraError(message)

        source = _latest_image(temp_path)
        target = _target_path(source.name)
        shutil.move(str(source), target)
        return target


def _release_macos_camera_helpers() -> None:
    if platform.system().lower() != "darwin":
        return

    for process_name in MACOS_CAMERA_HELPERS:
        subprocess.run(
            ["killall", process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def _detected_gphoto2_camera(gp, context) -> tuple[str, str]:
    camera_list = gp.Camera.autodetect(context)
    if camera_list.count() == 0:
        raise CameraError(
            "No gphoto2 camera was detected. Set the Sony USB mode to Remote Shooting, "
            "close apps using the camera, then unplug and reconnect the USB cable."
        )

    return camera_list.get_name(0), camera_list.get_value(0)


def _configure_gphoto2_camera(gp, context, model: str, port: str):
    camera = gp.Camera()

    abilities_list = gp.CameraAbilitiesList()
    abilities_list.load(context)
    camera.set_abilities(abilities_list.get_abilities(abilities_list.lookup_model(model)))

    port_info_list = gp.PortInfoList()
    port_info_list.load()
    camera.set_port_info(port_info_list.get_info(port_info_list.lookup_path(port)))

    return camera


def _camera_error_message(exc: Exception, model: str | None = None, port: str | None = None) -> str:
    message = str(exc)
    camera = f" {model} on {port}" if model and port else ""

    if "[-53]" in message or "Could not claim the USB device" in message:
        return (
            f"Camera detected{camera}, but macOS would not release the USB device. "
            "Close FaceTime, Photos, Image Capture, and browser camera tabs; unplug/reconnect the Sony directly to the Mac "
            "instead of through a dock; then try again."
        )

    if "[-105]" in message or "Unknown model" in message:
        return (
            "The Sony is not presenting itself as a remote-shooting camera. "
            "Set USB mode to Remote Shooting, then unplug and reconnect the USB cable."
        )

    return f"Camera communication failed: {message}"


def _capture_with_python_gphoto2() -> Path:
    try:
        import gphoto2 as gp
    except ImportError as exc:
        raise CameraError("python-gphoto2 is not installed. Run pip install -r requirements.txt after installing libgphoto2.") from exc

    context = gp.Context()
    camera = None
    model = None
    port = None

    try:
        model, port = _detected_gphoto2_camera(gp, context)
        _release_macos_camera_helpers()
        camera = _configure_gphoto2_camera(gp, context, model, port)
        camera.init(context)
        file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
        if not getattr(file_path, "folder", None) or not getattr(file_path, "name", None):
            raise CameraError("The camera did not report a captured file path.")

        camera_file = camera.file_get(file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
        target = _target_path(file_path.name)
        camera_file.save(str(target))
        return target
    except CameraError:
        raise
    except gp.GPhoto2Error as exc:
        raise CameraError(_camera_error_message(exc, model, port)) from exc
    finally:
        if camera is not None:
            try:
                camera.exit(context)
            except Exception:
                pass


def capture_image() -> Path:
    if platform.system().lower() == "windows":
        return _capture_with_gphoto2_cli()
    return _capture_with_python_gphoto2()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/capture")
async def capture() -> dict[str, str]:
    try:
        image_path = await asyncio.wait_for(asyncio.to_thread(capture_image), timeout=CAPTURE_TIMEOUT_SECONDS + 5)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Camera capture timed out.") from exc
    except CameraError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"image_url": f"/captured_photos/{image_path.name}"}
