# 一次性把 OpenAI Key 写入 ~/.Zeloo/.env
# 用法：.\set_openai_key.ps1 -Key "sk-你的真实key"
param(
    [Parameter(Mandatory=$true)][string]$Key
)
$envFile = "$env:USERPROFILE\.Zeloo\.env"
if (-not (Test-Path $envFile)) { New-Item -ItemType File -Path $envFile -Force | Out-Null }
$content = Get-Content $envFile -ErrorAction SilentlyContinue
$masked  = ($Key.Substring(0,[Math]::Min(7,$Key.Length)) + '...' + $Key.Substring([Math]::Max(0,$Key.Length-4)))
$line    = "OPENAI_API_KEY=$Key"
if ($content -match '^OPENAI_API_KEY=') {
    $content = $content -replace '^OPENAI_API_KEY=.*$', $line
    Set-Content -Path $envFile -Value $content -Encoding UTF8
} else {
    Add-Content -Path $envFile -Value $line -Encoding UTF8
}
Write-Host "✅ OPENAI_API_KEY written to $envFile (preview: $masked)"
