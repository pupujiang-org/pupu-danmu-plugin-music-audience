"""Validate and deterministically package static plugin data; never executes it.

Official plugins are MIT-licensed. `--check` and packaging both fail when the
repository LICENSE, a plugin LICENSE, or a manifest `license` field stops
matching that policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
ALLOWED_ROOT_FILES = {
    "manifest.json",
    "README.md",
    "LICENSE",
    "personas.json",
    "topics.json",
    "participation.json",
}
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_PROMPT_BYTES = 64 * 1024
MIT_LICENSE = "MIT"
MIT_LICENSE_TEXT = """MIT License

Copyright (c) 2026 Pupujiang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _normalized_text(payload: bytes, *, subject: str) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{subject} must be UTF-8 text") from None
    return text.replace("\r\n", "\n")


def _require_mit_license_text(payload: bytes, *, subject: str) -> None:
    if _normalized_text(payload, subject=subject) != MIT_LICENSE_TEXT:
        raise ValueError(f"{subject} must contain the MIT license text")


def _validate_repository_license() -> None:
    try:
        payload = (ROOT / "LICENSE").read_bytes()
    except OSError:
        raise ValueError("repository LICENSE is missing") from None
    _require_mit_license_text(payload, subject="repository LICENSE")


def _validate_no_tracked_release_assets() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked_assets = [
        path.decode("utf-8", errors="replace")
        for path in result.stdout.split(b"\0")
        if path.lower().endswith((b".zip", b".zip.sha256"))
    ]
    if tracked_assets:
        raise ValueError(
            "release assets must not be committed: " + ", ".join(tracked_assets)
        )


def _load_manifest(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    if not payload or len(payload) > 64 * 1024:
        raise ValueError("manifest size is outside the supported limit")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    required = {
        "schema_version",
        "id",
        "name",
        "version",
        "description",
        "author",
        "license",
        "min_host_version",
        "kind",
        "runtime_type",
        "plugin_api_version",
        "capabilities",
        "config_schema",
        "recommended_pacing",
        "resources",
    }
    if set(value) != required:
        raise ValueError("manifest fields are missing or unsupported")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported manifest schema")
    slug = value.get("id")
    version = value.get("version")
    if not isinstance(slug, str) or not re.fullmatch(
        r"org\.[a-z0-9-]+\.[a-z0-9][a-z0-9-]*", slug
    ):
        raise ValueError("plugin id must be a namespaced lowercase id")
    if slug.rsplit(".", 1)[-1] != path.parent.name:
        raise ValueError("plugin id suffix must match its source directory")
    if not isinstance(version, str) or SEMVER.fullmatch(version) is None:
        raise ValueError("plugin version must use SemVer")
    if value.get("license") != MIT_LICENSE:
        raise ValueError(f"official plugin license must be {MIT_LICENSE}")
    if value.get("kind") != "ai-participation":
        raise ValueError("unsupported plugin kind")
    if (
        value.get("runtime_type") != "declarative"
        or type(value.get("plugin_api_version")) is not int
        or value["plugin_api_version"] != 1
    ):
        raise ValueError("unsupported plugin runtime or API version")
    capabilities = value.get("capabilities")
    if (
        not isinstance(capabilities, list)
        or len(capabilities) > 16
        or not all(isinstance(item, str) for item in capabilities)
        or len(set(capabilities)) != len(capabilities)
    ):
        raise ValueError("capabilities must be a unique list")
    if not set(capabilities).issubset(
        {"chat_context", "host_llm", "persona", "topic_hints"}
    ):
        raise ValueError("unsupported plugin capability")
    if not isinstance(value.get("config_schema"), dict):
        raise ValueError("config_schema must be an object")
    pacing = value.get("recommended_pacing")
    if not isinstance(pacing, dict) or not set(pacing).issubset(
        {"min_interval_seconds", "max_interval_seconds", "hourly_limit"}
    ):
        raise ValueError("recommended_pacing is invalid")
    if not isinstance(value.get("resources"), dict):
        raise ValueError("resources must be an object")
    resources = value["resources"]
    if len(resources) > 4:
        raise ValueError("resources exceed the item limit")
    for kind, resource_path in resources.items():
        if not isinstance(kind, str) or not isinstance(resource_path, str):
            raise ValueError("resource references must be text")
        if kind == "prompt":
            valid = (
                resource_path.startswith("prompts/")
                and resource_path.endswith((".txt", ".md"))
                and resource_path.count("/") == 1
            )
        else:
            valid = {
                "personas": "personas.json",
                "topics": "topics.json",
                "participation": "participation.json",
            }.get(kind) == resource_path
        if not valid:
            raise ValueError("resource reference is outside the static package layout")
    if len(value["config_schema"]) > 32:
        raise ValueError("config_schema exceeds the item limit")
    return value


def _package_files(directory: Path, manifest: dict[str, object]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen_casefolded_paths: set[str] = set()
    total_bytes = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed: {path.relative_to(directory)}")
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        folded = relative.casefold()
        if folded in seen_casefolded_paths:
            raise ValueError(f"case-insensitive duplicate package path: {relative}")
        seen_casefolded_paths.add(folded)
        if relative not in ALLOWED_ROOT_FILES and not (
            relative.startswith("prompts/")
            and relative.count("/") == 1
            and relative.endswith((".txt", ".md"))
        ):
            raise ValueError(f"unsupported package file: {relative}")
        content = path.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"package file exceeds size limit: {relative}")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("package expands beyond the size limit")
        files[relative] = content

    declared = manifest["resources"]
    assert isinstance(declared, dict)
    if not all(
        isinstance(kind, str) and isinstance(resource_path, str)
        for kind, resource_path in declared.items()
    ):
        raise ValueError("manifest resource paths must be text")
    if any(path not in files for path in declared.values()):
        raise ValueError("manifest references a missing package resource")
    if len(files) > 100:
        raise ValueError("package contains too many files")
    for kind, resource_path in declared.items():
        content = files[resource_path]
        if kind == "prompt":
            if len(content) > MAX_PROMPT_BYTES:
                raise ValueError("prompt resource exceeds the size limit")
            try:
                prompt = content.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("prompt resource must be UTF-8") from None
            if "\x00" in prompt:
                raise ValueError("prompt resource contains invalid text")
        else:
            _validate_json_resource(content)
    if "manifest.json" not in files:
        raise ValueError("plugin source has no manifest.json")
    license_payload = files.get("LICENSE")
    if license_payload is None:
        raise ValueError("plugin package must include its LICENSE file")
    _require_mit_license_text(license_payload, subject="plugin LICENSE")
    return files


def _validate_json_resource(payload: bytes) -> None:
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("JSON resources must have an object root")


def _build_archive(files: dict[str, bytes]) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    payload = output.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("compressed plugin archive exceeds the size limit")
    return payload


def _plugin_directories(requested: str | None) -> list[Path]:
    directories = sorted(path for path in PLUGINS.iterdir() if path.is_dir())
    if requested is None:
        return directories
    matching = [path for path in directories if path.name == requested]
    if not matching:
        raise ValueError(f"unknown plugin slug: {requested}")
    return matching


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate all packages and the MIT license policy",
    )
    parser.add_argument("--plugin", help="package one plugin by directory slug")
    parser.add_argument(
        "--output", type=Path, help="directory for ZIP and SHA-256 files"
    )
    parser.add_argument("--expected-version", help="require this exact release version")
    args = parser.parse_args(argv)
    if not args.check and args.output is None:
        parser.error("--output is required unless --check is used")

    try:
        _validate_repository_license()
        if args.check:
            _validate_no_tracked_release_assets()
        directories = _plugin_directories(args.plugin)
        if not directories:
            raise ValueError("no plugin sources found")
        for directory in directories:
            manifest = _load_manifest(directory / "manifest.json")
            files = _package_files(directory, manifest)
            payload = _build_archive(files)
            version = manifest["version"]
            if args.expected_version is not None and version != args.expected_version:
                raise ValueError("tag version does not match plugin manifest")
            if not args.check:
                assert args.output is not None
                args.output.mkdir(parents=True, exist_ok=True)
                slug = directory.name
                archive_path = args.output / f"{slug}-{version}.zip"
                archive_path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                (args.output / f"{archive_path.name}.sha256").write_text(
                    f"{digest}  {archive_path.name}\n", encoding="ascii"
                )
                print(f"{archive_path} sha256={digest}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"plugin validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
