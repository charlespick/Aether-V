#!/usr/bin/env python3
"""Collect license information from Python and JavaScript dependencies.

This script uses pip-licenses (for Python) and license-checker (for JavaScript)
to gather license information for all project dependencies, including transitive
dependencies. The output is a JSON document that can be packaged into the
container and served via the API.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def collect_python_licenses() -> list[dict[str, Any]]:
    """Collect license information from Python packages using pip-licenses."""
    packages = []
    
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "piplicenses",
                "--format=json",
                "--with-urls",
                "--with-authors",
                "--with-license-file",
                "--no-license-path",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        
        raw_packages = json.loads(result.stdout)
        
        for pkg in raw_packages:
            packages.append({
                "name": pkg.get("Name", ""),
                "version": pkg.get("Version", ""),
                "license": pkg.get("License", "Unknown"),
                "author": pkg.get("Author", ""),
                "url": pkg.get("URL", ""),
                "ecosystem": "python",
            })
    except subprocess.CalledProcessError as e:
        print(f"Warning: pip-licenses failed: {e.stderr}", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse pip-licenses output: {e}", file=sys.stderr)
    except FileNotFoundError:
        print("Warning: pip-licenses not installed, skipping Python license collection", file=sys.stderr)
    
    return packages


def collect_js_licenses(package_dir: Path) -> list[dict[str, Any]]:
    """Collect license information from JavaScript packages using license-checker."""
    packages: list[dict[str, Any]] = []
    
    node_modules = package_dir / "node_modules"
    if not node_modules.exists():
        print("Warning: node_modules not found, skipping JavaScript license collection", file=sys.stderr)
        return packages
    
    try:
        result = subprocess.run(
            ["npx", "license-checker", "--json", "--production"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(package_dir),
        )
        
        raw_packages = json.loads(result.stdout)
        
        for full_name, info in raw_packages.items():
            # Parse package name and version from the key (format: "package@version")
            if "@" in full_name:
                # Handle scoped packages like @org/package@version
                if full_name.startswith("@"):
                    # Scoped package: find the last @ for version
                    at_idx = full_name.rfind("@")
                    name = full_name[:at_idx]
                    version = full_name[at_idx + 1:]
                else:
                    name, version = full_name.rsplit("@", 1)
            else:
                name = full_name
                version = ""
            
            # Extract publisher/author information
            author = ""
            if isinstance(info.get("publisher"), str):
                author = info["publisher"]
            elif isinstance(info.get("email"), str):
                author = info["email"]
            
            packages.append({
                "name": name,
                "version": version,
                "license": info.get("licenses", "Unknown"),
                "author": author,
                "url": info.get("repository", "") or info.get("url", ""),
                "ecosystem": "javascript",
            })
    except subprocess.CalledProcessError as e:
        print(f"Warning: license-checker failed: {e.stderr}", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse license-checker output: {e}", file=sys.stderr)
    except FileNotFoundError:
        print("Warning: npx not found, skipping JavaScript license collection", file=sys.stderr)
    
    return packages


def main() -> None:
    """Collect all licenses and write to JSON file."""
    # Determine paths
    script_dir = Path(__file__).resolve().parent
    server_dir = script_dir.parent
    output_path = server_dir / "oss-licenses.json"
    
    # Collect licenses from both ecosystems
    python_packages = collect_python_licenses()
    js_packages = collect_js_licenses(server_dir)
    
    # Combine and sort by name
    all_packages = python_packages + js_packages
    all_packages.sort(key=lambda x: (x.get("ecosystem", ""), x.get("name", "").lower()))
    
    # Create the output document
    output = {
        "packages": all_packages,
        "summary": {
            "total": len(all_packages),
            "python": len(python_packages),
            "javascript": len(js_packages),
        },
    }
    
    # Write to file
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Collected {len(all_packages)} package licenses -> {output_path}")


if __name__ == "__main__":
    main()
