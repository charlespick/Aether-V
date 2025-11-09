import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_ICONS_DIR = ROOT / "app" / "static" / "icons"
ICON_SOURCES = [
    (ROOT / "node_modules" / "@material-symbols" / "svg-400", {
        "round": "rounded",
    }),
]


def clean_static_icons():
    if STATIC_ICONS_DIR.exists():
        for child in STATIC_ICONS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def copy_icon(style: str, icon_name: str) -> bool:
    destination = STATIC_ICONS_DIR / style / f"{icon_name}.svg"

    for base_dir, style_map in ICON_SOURCES:
        mapped_style = style_map.get(style, style)
        source = base_dir / mapped_style / f"{icon_name}.svg"

        if not source.exists():
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"[copy] {style}/{icon_name}.svg")
        return True

    print(f"[warn] missing icon: {style}/{icon_name}.svg")
    return False


def main():
    config_path = ROOT / "icons.json"
    if not config_path.exists():
        raise SystemExit(
            "icons.json not found. Create it before running this script.")

    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    clean_static_icons()
    copied = 0
    missing = []

    for style, icons in config.items():
        for icon_name in icons:
            if copy_icon(style, icon_name):
                copied += 1
            else:
                missing.append((style, icon_name))

    print(
        f"[done] copied {copied} icons to {STATIC_ICONS_DIR.relative_to(ROOT)}")
    if missing:
        print("[warn] missing icons:")
        for style, icon_name in missing:
            print(f"  - {style}/{icon_name}")


if __name__ == "__main__":
    main()
