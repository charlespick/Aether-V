# UI Development Notes

## Icon management
- Icons used by the dashboard are enumerated in `server/icons.json`. Keep this list focused on the icons that are actually referenced in the templates, stylesheets, and client-side scripts so we do not ship unused assets.
- Run `npm install` inside `server/` to ensure the icon packages listed in `package.json` are available.
- Execute `python server/scripts/extract_icons.py` from the repository root after updating the manifest. The script now copies icons from both `@material-design-icons/svg` and `@material-symbols/svg-400` (for styles such as `round` → `rounded`), so new icons like `host` and `circles_ext` are picked up automatically.
- If the script warns that an icon is missing, verify the icon exists in one of the packages above or add an explicit asset before relying on it in the UI.

Keeping this workflow documented helps prevent icons from being referenced in the UI without being bundled into the static assets.
