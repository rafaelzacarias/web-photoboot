# Sony α7 IV Web Photobooth

A local, browser-based DIY photo booth for a Sony α7 IV connected by USB in PC Remote mode. The FastAPI backend triggers the real camera shutter and downloads each capture into `captured_photos/`; the single-page frontend provides a full-screen tap-to-start flow with countdown, flash, and review screens.

## Requirements

- Python 3.10+
- Sony α7 IV connected over USB-C
- Camera set to **PC Remote** mode
- One backend binding:
  - **macOS/Linux:** install system `libgphoto2` and use the pinned Python `gphoto2` wrapper from `requirements.txt`.
  - **Windows 11:** install the native `gphoto2.exe` CLI binary. The app intentionally avoids `python-gphoto2` on Windows and wraps `gphoto2.exe` with `subprocess` instead.

## Sony α7 IV camera settings

On the camera, set:

1. `Menu` → `Network` → `Transfer/Remote` → `PC Remote Function` → **On**
2. `PC Remote Cnct Method` → **USB**
3. `PC Remote Shoot Setting` → **Still Img. Save Dest.** → **PC Only** or **PC+Camera**
4. `USB Connection Mode` / `USB Connection` → **PC Remote**
5. Disable sleep/power saving while the booth is running.
6. Connect the camera directly to the laptop over USB and turn the camera on before starting the server.

Menu wording can vary slightly by firmware version, but the required state is USB PC Remote shooting enabled.

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Platform notes

macOS:

```bash
brew install libgphoto2
python -m pip install -r requirements.txt
```

Linux:

```bash
sudo apt-get install libgphoto2-dev gphoto2
python -m pip install -r requirements.txt
```

Windows 11:

1. Install a native `gphoto2.exe` build.
2. Add the folder containing `gphoto2.exe` to `PATH`, or set `GPHOTO2_BIN` to its full path.
3. Run `python -m pip install -r requirements.txt`. The `gphoto2` Python package is skipped automatically on Windows.

## Run

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> in a browser and use full-screen mode for the booth UI.

## API

- `GET /` serves the photo booth interface.
- `POST /api/capture` triggers the Sony shutter, downloads the captured image, stores it in `captured_photos/`, and returns:

```json
{ "image_url": "/captured_photos/<timestamp>-<uuid>.jpg" }
```

## Troubleshooting

- If capture times out, confirm the camera is awake, in PC Remote USB mode, and no other app is connected to it.
- If no image appears, check that PC Remote save destination allows transfer to the computer.
- On Windows, run `gphoto2.exe --auto-detect` to verify the camera is visible.
- On macOS/Linux, run `gphoto2 --auto-detect` and confirm `libgphoto2` can see the camera.
- If startup fails with `jinja2 must be installed to use Jinja2Templates`, make sure the virtual environment is active and reinstall the app dependencies with `python -m pip install -r requirements.txt` using the same Python environment that runs `python -m uvicorn`.
- Increase the backend timeout with `PHOTOBOOTH_CAPTURE_TIMEOUT=60` if large RAW+JPEG transfers need more time.
