$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$runner = Join-Path $root 'tools\setup\RUN_PC_DRIVE_SYNC.cmd'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "PC Drive 동기화 실행 파일이 없습니다."
}
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/d /c `"$runner`"" -WorkingDirectory $root
$triggers = 7..23 | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ("{0:D2}:00" -f $_)
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'AuderyAI Stock Drive Delta Sync' -Description '07:00~23:00 매시간 Google Drive의 검증된 일일 변경분만 로컬 PostgreSQL에 멱등 반영' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
Write-Host 'AuderyAI Stock Drive Delta Sync: 매일 07:00~23:00 매시간, 놓친 경우 다음 PC 사용 시 실행하도록 등록했습니다.'
