# Parse install.ps1 and print every error in full detail.
$path = Join-Path $PSScriptRoot "..\install.ps1"
$path = (Resolve-Path $path).Path
$errors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
Write-Host ("Tokens: {0}" -f $tokens.Count)
Write-Host ("Errors: {0}" -f $errors.Count)
foreach ($e in $errors) {
    $lineText = (Get-Content $path)[$e.Extent.StartLineNumber - 1]
    Write-Host ("L{0}:C{1} - {2}" -f $e.Extent.StartLineNumber, $e.Extent.StartColumnNumber, $e.Message)
    Write-Host ("    > {0}" -f $lineText)
    Write-Host ("    > {0}^" -f (' ' * ($e.Extent.StartColumnNumber - 1)))
}
