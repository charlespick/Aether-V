"""Extract Swagger UI static assets from node_modules."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWAGGER_UI_SOURCE = ROOT / "node_modules" / "swagger-ui-dist"
SWAGGER_UI_DEST = ROOT / "app" / "static" / "swagger-ui"

# Files needed for Swagger UI to work
REQUIRED_FILES = [
    "swagger-ui-bundle.js",
    "swagger-ui.css",
    "swagger-ui-standalone-preset.js",
    "favicon-32x32.png",
]


def extract_swagger_ui():
    """Extract required Swagger UI files from node_modules to static directory."""
    if not SWAGGER_UI_SOURCE.exists():
        raise SystemExit(
            f"swagger-ui-dist not found at {SWAGGER_UI_SOURCE}. "
            "Run 'npm install' first."
        )

    # Create destination directory
    SWAGGER_UI_DEST.mkdir(parents=True, exist_ok=True)

    copied = 0
    for filename in REQUIRED_FILES:
        source = SWAGGER_UI_SOURCE / filename
        dest = SWAGGER_UI_DEST / filename

        if not source.exists():
            print(f"[warn] missing file: {filename}")
            continue

        shutil.copy2(source, dest)
        print(f"[copy] {filename} ({source.stat().st_size} bytes)")
        copied += 1

    print(f"[done] copied {copied}/{len(REQUIRED_FILES)} Swagger UI assets to {SWAGGER_UI_DEST.relative_to(ROOT)}")

    if copied != len(REQUIRED_FILES):
        raise SystemExit(f"Failed to copy all required files. Expected {len(REQUIRED_FILES)}, got {copied}")


if __name__ == "__main__":
    extract_swagger_ui()
