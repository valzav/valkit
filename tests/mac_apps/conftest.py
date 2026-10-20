import json
import plistlib
import shutil
from pathlib import Path
from typing import cast

import pytest

from valkit.mac_apps.model import Inventory
from valkit.mac_apps.runner import CommandError, Runner
from valkit.mac_apps.scan import scan


class FakeMac:
    """Synthetic application bundles plus a fake runner for `mo`, `brew`, `mas`, `mdls`,
    and `du`. Removal commands delete the synthetic bundles they target."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = root / "store"
        self.nix_apps = root / "Home Manager Apps"
        self.entries: list[dict[str, str]] = []
        self.casks: list[dict[str, object]] = []
        self.app_store_ids: dict[str, str] = {}
        self.disk_kb: dict[str, int] = {}
        self.calls: list[list[str]] = []
        self.package_files: dict[str, list[str]] = {}
        self.failing: set[str] = set()
        """Removal commands whose last argument is listed here fail."""
        self.inert: set[str] = set()
        """Removal commands whose last argument is listed here succeed but remove nothing,
        as `mo uninstall` does when it aborts."""

    def add(
        self,
        name: str,
        bundle_id: str,
        *,
        size: str = "10.0MB",
        cask: str | None = None,
        cask_zap: str | None = None,
        mole_source: str = "App",
        app_store_id: str | None = None,
        in_store: bool = False,
        disk_kb: int | None = None,
        folder: str = "Applications",
    ) -> Path:
        bundle = self._bundle(name, bundle_id, in_store, folder)
        path = bundle
        if in_store:
            path = self.root / "Linked" / f"{name}.app"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(bundle)
        if app_store_id is not None:
            (bundle / "Contents" / "_MASReceipt").mkdir()
            (bundle / "Contents" / "_MASReceipt" / "receipt").write_bytes(b"receipt")
            self.app_store_ids[str(path)] = app_store_id
        if cask is not None:
            self.casks.append(
                {
                    "token": cask,
                    "artifacts": [
                        {"app": [f"{name}.app"], "target": str(path)},
                        # A cask names its app's bundle ID in the files its zap trashes.
                        {
                            "zap": [
                                {"trash": [cask_zap or f"~/Library/Preferences/{bundle_id}.plist"]}
                            ]
                        },
                    ],
                }
            )
        if disk_kb is not None:
            self.disk_kb[str(path)] = disk_kb
        self.entries.append(
            {
                "name": name,
                "bundle_id": bundle_id,
                "source": mole_source,
                "uninstall_name": cask if mole_source == "Homebrew" and cask else name,
                "path": str(path),
                "size": size,
            }
        )
        return path

    def add_nix_app(self, name: str, bundle_id: str, disk_kb: int) -> Path:
        bundle = self._bundle(name, bundle_id, in_store=True)
        self.nix_apps.mkdir(exist_ok=True)
        path = self.nix_apps / f"{name}.app"
        path.symlink_to(bundle)
        self.disk_kb[str(path)] = disk_kb
        return path

    def _bundle(
        self, name: str, bundle_id: str, in_store: bool, folder: str = "Applications"
    ) -> Path:
        bundle = (self.store if in_store else self.root / folder) / f"{name}.app"
        (bundle / "Contents").mkdir(parents=True)
        with (bundle / "Contents" / "Info.plist").open("wb") as file:
            plistlib.dump({"CFBundleIdentifier": bundle_id}, file)
        return bundle

    def add_package_cask(self, token: str, packages: dict[str, list[str]]) -> None:
        """A cask that installs .pkg files: brew names the receipts, not the apps."""
        self.package_files.update(packages)
        self.casks.append(
            {"token": token, "artifacts": [{"uninstall": [{"pkgutil": list(packages)}]}]}
        )

    def add_cask_without_app(self, token: str) -> None:
        self.casks.append({"token": token, "artifacts": [{"binary": [token]}]})

    def _delete(self, path: str) -> None:
        shutil.rmtree(path)
        self.entries = [entry for entry in self.entries if entry["path"] != path]

    def _remove(self, command: list[str], stdin: str | None) -> str:
        self.calls.append(command)
        target = command[-1]
        if target in self.failing:
            raise CommandError(f"{' '.join(command)} failed (1): synthetic failure")
        if target in self.inert:
            return ""
        if command[:4] == ["brew", "uninstall", "--zap", "--cask"]:
            cask = next(cask for cask in self.casks if cask["token"] == target)
            self.casks.remove(cask)
            for artifact in cast(list[dict[str, object]], cask["artifacts"]):
                if isinstance(artifact.get("target"), str):
                    self._delete(cast(str, artifact["target"]))
        elif command[:3] == ["sudo", "mas", "uninstall"]:
            for path, app_id in list(self.app_store_ids.items()):
                if app_id == target:
                    self._delete(path)
        elif command[:2] == ["mo", "uninstall"] and stdin == "y\n":
            for entry in list(self.entries):
                if entry["uninstall_name"] == target:
                    self._delete(entry["path"])
                    break
        return ""

    @property
    def run(self) -> Runner:
        def run(command: list[str], stdin: str | None = None) -> str:
            if command == ["mo", "uninstall", "--list"]:
                return json.dumps(self.entries)
            if command == ["brew", "info", "--installed", "--cask", "--json=v2"]:
                return json.dumps({"formulae": [], "casks": self.casks})
            if command[:4] == ["mdls", "-raw", "-name", "kMDItemAppStoreAdamID"]:
                return self.app_store_ids.get(command[4], "(null)")
            if command[:2] == ["pkgutil", "--files"]:
                if command[2] not in self.package_files:
                    raise CommandError(f"No receipt for '{command[2]}' found at '/'.")
                return "\n".join(self.package_files[command[2]]) + "\n"
            if command[:2] == ["du", "-skH"]:
                return f"{self.disk_kb[command[2]]}\t{command[2]}\n"
            if command[:2] in (["brew", "uninstall"], ["sudo", "mas"], ["mo", "uninstall"]):
                return self._remove(command, stdin)
            raise AssertionError(f"unexpected command {command}")

        return run

    def scan(self) -> Inventory:
        return scan(self.run, nix_store=self.store, nix_app_dirs=(self.nix_apps,))


@pytest.fixture
def mac(tmp_path: Path) -> FakeMac:
    return FakeMac(tmp_path)
