from pathlib import Path

install_ps1 = Path(__file__).resolve().parent / "install.ps1"
content = (
    "$ErrorActionPreference = 'SilentlyContinue'\n"
    "$t = $null; $e = $null\n"
    "[void][System.Management.Automation.Language.Parser]::ParseFile(\n"
    "    '{ps1}',\n"
    "    [ref]$t,\n"
    "    [ref]$e\n"
    ")\n"
    "if ($e) {\n"
    "    Write-Host 'PARSE_ERRORS:' $e.Count\n"
    "    exit 1\n"
    "} else {\n"
    "    Write-Host 'PARSE_OK'\n"
    "    exit 0\n"
    "}\n"
).format(ps1=str(install_ps1))

(Path(__file__).resolve().parent / "_generated_check.ps1").write_text(content, encoding="utf-8")
print("Written to _generated_check.ps1")
print("Path length:", len(str(install_ps1)))
print("Path:", str(install_ps1))
