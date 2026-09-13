from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    # The launchers live in the managed binary dir OUTSIDE the git checkout
    # (ZELOO_HOME\bin, next to the managed uv) — NOT the whole venv\Scripts
    # (which would shadow the user's python, #83797) and NOT a dir inside
    # the checkout (which `Zeloo update`'s autostash swept off disk).
    assert "%LOCALAPPDATA%\\Zeloo\\bin" in doc
    assert (
        "Get-Command Zeloo        # should print "
        "C:\\Users\\<you>\\AppData\\Local\\Zeloo\\bin\\Zeloo.exe"
    ) in doc
    # Installer exposes $ZELOOHome\bin, and must copy the launchers into it.
    assert '$ZELOOBin = "$ZELOOHome\\bin"' in install
    assert "Zeloo.exe" in install and "Zeloo-acp.exe" in install
    # Guard against regressions to either legacy layout.
    assert '$ZELOOBin = "$InstallDir\\venv\\Scripts"' not in install
    assert '$ZELOOBin = "$InstallDir\\bin"' not in install
