import json
from typing import Any, cast

from valkit.mac_apps.model import Manifest, ManualApp


class ManifestError(ValueError):
    pass


def parse_manifest(text: str) -> Manifest:
    """Parse the manifest JSON.

    {"casks": {token: {"dir": ...}}, "mas": {name: id},
     "manual": {name: {"bundleId": ..., "url": ..., "dir": ...}}, "dock": [path, ...]}
    """
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise ManifestError(f"manifest is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    root = cast(dict[str, Any], data)
    missing = {"casks", "mas", "manual", "dock"} - root.keys()
    if missing:
        raise ManifestError(f"manifest is missing {', '.join(sorted(missing))}")
    return Manifest(
        casks=_casks(root["casks"]),
        mas=_mas(root["mas"]),
        manual=_manual(root["manual"]),
        dock=tuple(_string_list(root["dock"], "dock")),
    )


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ManifestError(f"{field} must be a list")
    items = cast(list[Any], value)
    if not all(isinstance(item, str) for item in items):
        raise ManifestError(f"{field} must hold strings")
    return cast(list[str], items)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _casks(value: Any) -> dict[str, str]:
    casks: dict[str, str] = {}
    for token, entry in _object(value, "casks").items():
        directory = _object(entry, f"casks.{token}").get("dir")
        if not isinstance(directory, str):
            raise ManifestError(f"casks.{token} needs a string dir")
        casks[token] = directory
    return casks


def _mas(value: Any) -> dict[str, int]:
    entries = _object(value, "mas")
    for name, app_id in entries.items():
        if not isinstance(app_id, int) or isinstance(app_id, bool):
            raise ManifestError(f"mas.{name} must be an App Store ID number")
    return cast(dict[str, int], entries)


def _manual(value: Any) -> dict[str, ManualApp]:
    apps: dict[str, ManualApp] = {}
    for name, entry in _object(value, "manual").items():
        fields = _object(entry, f"manual.{name}")
        bundle_id = fields.get("bundleId")
        url = fields.get("url")
        directory = fields.get("dir")
        if not all(isinstance(field, str) for field in (bundle_id, url, directory)):
            raise ManifestError(f"manual.{name} needs string bundleId, url, and dir")
        apps[name] = ManualApp(
            bundle_id=cast(str, bundle_id), url=cast(str, url), dir=cast(str, directory)
        )
    return apps


def manifest_json(manifest: Manifest) -> str:
    """The manifest in the same JSON shape `parse_manifest` reads."""
    data = {
        "casks": {token: {"dir": directory} for token, directory in sorted(manifest.casks.items())},
        "mas": dict(sorted(manifest.mas.items())),
        "manual": {
            name: {"bundleId": app.bundle_id, "url": app.url, "dir": app.dir}
            for name, app in sorted(manifest.manual.items())
        },
        "dock": list(manifest.dock),
    }
    return json.dumps(data, indent=2) + "\n"
