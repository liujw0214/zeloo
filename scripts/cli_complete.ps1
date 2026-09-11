# Zeloo CLI PowerShell Tab Completion
# Save to: $PROFILE directory (e.g. ~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1)
# Then add: . "$env:USERPROFILE\Documents\PowerShell\zeloo_complete.ps1"
# Or save directly to the profile: Add-Content -Path $PROFILE -Value ". '.\scripts\cli_complete.ps1'"

$ZelooSubcommands = @(
    "chat", "config", "install", "doctor", "status", "backup",
    "model", "skills", "session", "mcp", "usage", "tools", "update", "oauth"
)

$ZelooConfigKeys = @(
    "model", "provider", "temperature", "max_iterations",
    "profile", "mcp_servers", "web_provider", "memory_provider"
)

$ZelooConfigActions = @("show", "get", "set")

function ZelooCompletion {
    param(
        [string]$CommandName,
        [string]$ParameterName,
        [string]$WordToComplete,
        [System.Management.Automation.Language.CommandAst]$CommandAst,
        [System.Management.Automation.Language.IDsToComplete]$idsToComplete
    )

    $subcommands = $script:ZelooSubcommands
    $configActions = $script:ZelooConfigActions
    $configKeys = $script:ZelooConfigKeys

    switch ($ParameterName) {
        "command" {
            $subcommands | Where-Object { $_ -like "$WordToComplete*" } | ForEach-Object {
                [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterValue", $_)
            }
        }
        "action" {
            $configActions | Where-Object { $_ -like "$WordToComplete*" } | ForEach-Object {
                [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterValue", $_)
            }
        }
        "key" {
            $configKeys | Where-Object { $_ -like "$WordToComplete*" } | ForEach-Object {
                [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterValue", $_)
            }
        }
    }
}

# Register completions
$Options = @{
    CommandName = @("Zeloo", "zeloo")
    ParameterName = "command"
    Description = "Zeloo CLI subcommands"
    ScriptBlock = { ZelooCompletion @args }
}
Register-ArgumentCompleter @Options

$Options2 = @{
    CommandName = @("Zeloo", "zeloo")
    ParameterName = "action"
    Description = "Zeloo config actions"
    ScriptBlock = { ZelooCompletion @args }
}
Register-ArgumentCompleter @Options2

$Options3 = @{
    CommandName = @("Zeloo", "zeloo")
    ParameterName = "key"
    Description = "Zeloo config keys"
    ScriptBlock = { ZelooCompletion @args }
}
Register-ArgumentCompleter @Options3
