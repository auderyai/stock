$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$runner = Join-Path $root 'KRX_Menu_Launcher\sync_opendart_financial_from_drive.cmd'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw 'OpenDART financial local sync runner is missing.'
}

$action = New-ScheduledTaskAction `
    -Execute 'cmd.exe' `
    -Argument "/d /c `"$runner`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName 'AuderyAI OpenDART Financial Local Sync' `
    -Description 'Every 10 minutes, apply only a complete verified financial year from Drive to local PostgreSQL.' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host 'AuderyAI OpenDART Financial Local Sync: registered every 10 minutes.'
