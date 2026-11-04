$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/IronkeepCompanion.ps1"

$failures = 0
function Check($Condition, $Name) {
    if ($Condition) { return }
    $script:failures++
    [Console]::Error.WriteLine("FAIL $Name")
}

$db = Read-SavedPath (Join-Path $PSScriptRoot 'sample-Ironkeep.lua')
$text = Format-Report (Get-Field $db 'session') '2026-11-01 12:00'
$want = @(
    'Ironkeep group',
    'Place: Hall of Thanes',
    'Started: 2026-11-01 12:00',
    '',
    'Name | Class | Role | Time | Status',
    'Ada Smith | Warrior | Tank | 20m | here',
    'Bram Holt | Priest | Healer | 10m | here',
    'Dain Frost | Mage | Damage | 5m | left',
    '',
    'format: ironkeep-group 1'
) -join "`n"
Check ($text -eq $want) "sample report`n$text"

$cleared = Read-Saved "IronkeepDB = { [`"lastReport`"] = `"Ironkeep group\n\nformat: ironkeep-group 1`" }`n"
Check ((Format-Saved $cleared) -eq "Ironkeep group`n`nformat: ironkeep-group 1") 'previous report'

$refused = $false
try { Read-Saved "IronkeepDB = { [`"session`"] = os.execute(`"rm`") }`n" } catch { $refused = $true }
Check $refused 'call refused'

$missing = $false
try { Read-Saved "SomethingElse = { }`n" } catch { $missing = $true }
Check $missing 'missing list'

$wow = Join-Path ([System.IO.Path]::GetTempPath()) ("ironkeep-companion-" + [guid]::NewGuid().ToString('N'))
$older = Join-Path $wow 'WTF/Account/Old/SavedVariables/Ironkeep.lua'
$newer = Join-Path $wow 'WTF/Account/New/SavedVariables/Ironkeep.lua'
New-Item -ItemType Directory -Force -Path (Split-Path $older) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $newer) | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'sample-Ironkeep.lua') $older
Copy-Item (Join-Path $PSScriptRoot 'sample-Ironkeep.lua') $newer
(Get-Item $older).LastWriteTimeUtc = [datetime]::SpecifyKind([datetime]'2000-01-01', 'Utc')
(Get-Item $newer).LastWriteTimeUtc = [datetime]::SpecifyKind([datetime]'2000-01-02', 'Utc')
Check ((Get-Newest (Get-SavedFiles $wow)) -eq $newer) 'newest file'
Remove-Item -Recurse -Force $wow

if ($failures -gt 0) {
    [Console]::Error.WriteLine("$failures failed")
    exit 1
}
Write-Output 'ok'
