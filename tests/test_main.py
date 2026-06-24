import sys
from unittest.mock import MagicMock, patch

import pytest

from src.main import force_unmount_fuse_point, main


def test_main_no_args(capsys):
    with patch.object(sys, "argv", ["main.py"]), patch.dict("os.environ", clear=True):
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
        out, _ = capsys.readouterr()
        assert "Uso:" in out


def test_main_no_credentials():
    with patch.object(
        sys, "argv", ["main.py", "/tmp/mount", "invalid.json"]
    ), patch.dict("os.environ", clear=True), patch(
        "src.main.force_unmount_fuse_point"
    ), patch(
        "time.sleep"
    ):
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1


def test_main_success(tmp_path):
    cred = tmp_path / "cred.json"
    cred.write_text("{}")

    with patch.object(
        sys, "argv", ["main.py", str(tmp_path / "mount"), str(cred)]
    ), patch.dict("os.environ", clear=True), patch(
        "src.main.force_unmount_fuse_point"
    ), patch(
        "time.sleep"
    ), patch(
        "src.main.GoogleDriveStorageClient"
    ), patch(
        "src.main.MemoryMetadataCache"
    ), patch(
        "src.main.FuseOps"
    ), patch(
        "src.main.FUSE"
    ) as mock_fuse:
        main()
        mock_fuse.assert_called_once()


def test_main_keyboard_interrupt(tmp_path):
    cred = tmp_path / "cred.json"
    cred.write_text("{}")

    with patch.object(
        sys, "argv", ["main.py", str(tmp_path / "mount"), str(cred)]
    ), patch.dict("os.environ", clear=True), patch(
        "src.main.force_unmount_fuse_point"
    ), patch(
        "time.sleep"
    ), patch(
        "src.main.GoogleDriveStorageClient"
    ), patch(
        "src.main.MemoryMetadataCache"
    ), patch(
        "src.main.FuseOps"
    ), patch(
        "src.main.FUSE", side_effect=KeyboardInterrupt
    ):
        main()


def test_main_runtime_error(tmp_path):
    cred = tmp_path / "cred.json"
    cred.write_text("{}")

    with patch.object(
        sys, "argv", ["main.py", str(tmp_path / "mount"), str(cred)]
    ), patch.dict("os.environ", clear=True), patch(
        "src.main.force_unmount_fuse_point"
    ), patch(
        "time.sleep"
    ), patch(
        "src.main.GoogleDriveStorageClient"
    ), patch(
        "src.main.MemoryMetadataCache"
    ), patch(
        "src.main.FuseOps"
    ), patch(
        "src.main.FUSE", side_effect=RuntimeError("fuse err")
    ):
        main()


def test_unmount():
    with patch("os.system") as mock_system:
        force_unmount_fuse_point("/tmp/mount")
        mock_system.assert_called()
