# Reads the group list the WoW: Forever addon saved on this computer.
# The addon writes WTF\Account\<account>\SavedVariables\Ironkeep.lua on logout or /reload.
# This script does not start the game and does not send the list anywhere.

$ErrorActionPreference = 'Stop'

$script:RoleOrder = New-Object 'System.Collections.Generic.Dictionary[string,int]'
$script:RoleOrder['TANK'] = 1
$script:RoleOrder['HEALER'] = 2
$script:RoleOrder['DAMAGER'] = 3
$script:RoleLabel = New-Object 'System.Collections.Generic.Dictionary[string,string]'
$script:RoleLabel['TANK'] = 'Tank'
$script:RoleLabel['HEALER'] = 'Healer'
$script:RoleLabel['DAMAGER'] = 'Damage'
$script:Unreadable = 'This saved file could not be read.'
$script:CutOff = 'This saved file is cut off.'

function New-Table {
    return New-Object 'System.Collections.Generic.Dictionary[object,object]'
}

function New-Reader([string]$Text) {
    return @{ Text = $Text.TrimStart([char]0xFEFF); Index = 0 }
}

function Get-Peek($Reader) {
    if ($Reader.Index -ge $Reader.Text.Length) { return [char]0 }
    return $Reader.Text[$Reader.Index]
}

function Test-Starts($Reader, [string]$Token) {
    if ($Reader.Index + $Token.Length -gt $Reader.Text.Length) { return $false }
    return $Reader.Text.IndexOf($Token, $Reader.Index, [StringComparison]::Ordinal) -eq $Reader.Index
}

function Move-Skip($Reader) {
    while ($Reader.Index -lt $Reader.Text.Length) {
        $char = $Reader.Text[$Reader.Index]
        if ($char -eq ' ' -or $char -eq "`t" -or $char -eq "`r" -or $char -eq "`n") {
            $Reader.Index++
            continue
        }
        if (Test-Starts $Reader '--') {
            $Reader.Index += 2
            if (Test-Starts $Reader '[') {
                $mark = $Reader.Index
                $Reader.Index++
                $equals = 0
                while ((Get-Peek $Reader) -eq '=') { $equals++; $Reader.Index++ }
                if ((Get-Peek $Reader) -eq '[') {
                    $Reader.Index++
                    $close = ']' + ('=' * $equals) + ']'
                    $end = $Reader.Text.IndexOf($close, $Reader.Index, [StringComparison]::Ordinal)
                    if ($end -lt 0) { throw $script:CutOff }
                    $Reader.Index = $end + $close.Length
                    continue
                }
                $Reader.Index = $mark
            }
            $line = $Reader.Text.IndexOf("`n", $Reader.Index)
            if ($line -lt 0) { $Reader.Index = $Reader.Text.Length } else { $Reader.Index = $line + 1 }
            continue
        }
        return
    }
}

function Assert-Token($Reader, [string]$Token) {
    Move-Skip $Reader
    if (-not (Test-Starts $Reader $Token)) { throw $script:Unreadable }
    $Reader.Index += $Token.Length
}

function Test-Eat($Reader, [string]$Token) {
    Move-Skip $Reader
    if (-not (Test-Starts $Reader $Token)) { return $false }
    $Reader.Index += $Token.Length
    return $true
}

function Test-IdentStart([char]$Char) {
    return [char]::IsLetter($Char) -or $Char -eq '_'
}

function Read-Ident($Reader) {
    Move-Skip $Reader
    $start = $Reader.Index
    $char = Get-Peek $Reader
    if (-not (Test-IdentStart $char)) { throw $script:Unreadable }
    $Reader.Index++
    while ($Reader.Index -lt $Reader.Text.Length) {
        $char = $Reader.Text[$Reader.Index]
        if (-not ([char]::IsLetterOrDigit($char) -or $char -eq '_')) { break }
        $Reader.Index++
    }
    return $Reader.Text.Substring($start, $Reader.Index - $start)
}

function Read-Value($Reader) {
    Move-Skip $Reader
    $char = Get-Peek $Reader
    if ($char -eq '{') { return Read-Table $Reader }
    if ($char -eq '"' -or $char -eq "'") { return Read-Quote $Reader }
    if ($char -eq '[') { return Read-LongString $Reader }
    if ($char -eq '-' -or [char]::IsDigit($char)) { return Read-Number $Reader }
    if (Test-IdentStart $char) {
        $word = Read-Ident $Reader
        if ($word -ceq 'true') { return $true }
        if ($word -ceq 'false') { return $false }
        if ($word -ceq 'nil') { return $null }
        throw $script:Unreadable
    }
    throw $script:Unreadable
}

function Read-Table($Reader) {
    Assert-Token $Reader '{'
    $data = New-Table
    $index = 1
    while ($true) {
        Move-Skip $Reader
        if (Test-Eat $Reader '}') { return $data }
        if (Test-Eat $Reader '[') {
            $key = Read-Value $Reader
            Assert-Token $Reader ']'
            Assert-Token $Reader '='
            $data[$key] = Read-Value $Reader
        }
        elseif (Test-IdentStart (Get-Peek $Reader)) {
            $mark = $Reader.Index
            $name = Read-Ident $Reader
            if (Test-Eat $Reader '=') {
                $data[$name] = Read-Value $Reader
            }
            else {
                $Reader.Index = $mark
                $data[$index] = Read-Value $Reader
                $index++
            }
        }
        else {
            $data[$index] = Read-Value $Reader
            $index++
        }
        Move-Skip $Reader
        [void](Test-Eat $Reader ',')
        [void](Test-Eat $Reader ';')
    }
}

function Read-Quote($Reader) {
    $quote = Get-Peek $Reader
    $Reader.Index++
    $chars = New-Object System.Text.StringBuilder
    while ($Reader.Index -lt $Reader.Text.Length) {
        $char = $Reader.Text[$Reader.Index]
        if ($char -eq $quote) {
            $Reader.Index++
            return $chars.ToString()
        }
        if ($char -eq '\') {
            [void]$chars.Append((Read-Escape $Reader))
            continue
        }
        if ($char -eq "`n") { throw $script:Unreadable }
        [void]$chars.Append($char)
        $Reader.Index++
    }
    throw $script:CutOff
}

function Read-Escape($Reader) {
    $Reader.Index++
    if ($Reader.Index -ge $Reader.Text.Length) { throw $script:CutOff }
    $char = [string]$Reader.Text[$Reader.Index]
    $Reader.Index++
    switch ($char) {
        'a' { return "`a" }
        'b' { return "`b" }
        'f' { return "`f" }
        'n' { return "`n" }
        'r' { return "`r" }
        't' { return "`t" }
        'v' { return "`v" }
        '\' { return '\' }
        '"' { return '"' }
        "'" { return "'" }
        "`n" { return "`n" }
    }
    if ($char -ge '0' -and $char -le '9') {
        $digits = [string]$char
        for ($n = 0; $n -lt 2 -and $Reader.Index -lt $Reader.Text.Length; $n++) {
            $next = $Reader.Text[$Reader.Index]
            if ($next -lt '0' -or $next -gt '9') { break }
            $digits += $next
            $Reader.Index++
        }
        $code = [int]$digits
        if ($code -gt 255) { throw $script:Unreadable }
        return [string][char]$code
    }
    throw $script:Unreadable
}

function Read-LongString($Reader) {
    Assert-Token $Reader '['
    $equals = 0
    while (Test-Eat $Reader '=') { $equals++ }
    Assert-Token $Reader '['
    if ((Get-Peek $Reader) -eq "`n") { $Reader.Index++ }
    $close = ']' + ('=' * $equals) + ']'
    $end = $Reader.Text.IndexOf($close, $Reader.Index, [StringComparison]::Ordinal)
    if ($end -lt 0) { throw $script:CutOff }
    $value = $Reader.Text.Substring($Reader.Index, $end - $Reader.Index)
    $Reader.Index = $end + $close.Length
    return $value
}

function Read-Number($Reader) {
    $start = $Reader.Index
    if ((Get-Peek $Reader) -eq '-') { $Reader.Index++ }
    $saw = $false
    while ([char]::IsDigit((Get-Peek $Reader))) { $saw = $true; $Reader.Index++ }
    $floating = $false
    if ((Get-Peek $Reader) -eq '.') {
        $floating = $true
        $Reader.Index++
        while ([char]::IsDigit((Get-Peek $Reader))) { $saw = $true; $Reader.Index++ }
    }
    if (-not $saw) { throw $script:Unreadable }
    $token = $Reader.Text.Substring($start, $Reader.Index - $start)
    if ($floating) { return [double]::Parse($token, [Globalization.CultureInfo]::InvariantCulture) }
    return [long]::Parse($token, [Globalization.CultureInfo]::InvariantCulture)
}

function Read-Saved([string]$Text) {
    $reader = New-Reader $Text
    $found = New-Table
    while ($true) {
        Move-Skip $reader
        if ($reader.Index -ge $reader.Text.Length) { break }
        $name = Read-Ident $reader
        Assert-Token $reader '='
        $found[$name] = Read-Value $reader
    }
    $db = Get-Field $found 'IronkeepDB'
    if ($db -isnot [System.Collections.Generic.Dictionary[object,object]]) {
        throw 'This file has no Ironkeep list.'
    }
    return $db
}

function Read-SavedPath([string]$Path) {
    try {
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    }
    catch {
        throw "Could not open $Path."
    }
    return Read-Saved $text
}

function Get-Field($Table, [string]$Name) {
    if ($Table -isnot [System.Collections.Generic.Dictionary[object,object]]) { return $null }
    $value = $null
    if ($Table.TryGetValue($Name, [ref]$value)) { return $value }
    return $null
}

function Get-Number($Value) {
    if ($Value -is [long] -or $Value -is [int] -or $Value -is [double] -or $Value -is [decimal]) {
        return [double]$Value
    }
    return $null
}

function Get-SavedFiles([string]$WowDir) {
    $root = Join-Path (Join-Path $WowDir 'WTF') 'Account'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    $files = @()
    foreach ($account in Get-ChildItem -LiteralPath $root -Directory) {
        $path = Join-Path (Join-Path $account.FullName 'SavedVariables') 'Ironkeep.lua'
        if (Test-Path -LiteralPath $path -PathType Leaf) { $files += $path }
    }
    return @($files | Sort-Object)
}

function Get-Newest($Files) {
    $best = $null
    $bestTime = [datetime]::MinValue
    foreach ($file in $Files) {
        $when = (Get-Item -LiteralPath $file).LastWriteTimeUtc
        if ($null -eq $best -or $when -gt $bestTime) {
            $best = $file
            $bestTime = $when
        }
    }
    return $best
}

function Get-PersonKey($Person) {
    $present = 1
    if ((Get-Field $Person 'present') -eq $true) { $present = 0 }
    $group = 99.0
    $subgroup = Get-Number (Get-Field $Person 'subgroup')
    if ($null -ne $subgroup) { $group = $subgroup }
    $role = 9
    $roleName = [string](Get-Field $Person 'role')
    if ($script:RoleOrder.ContainsKey($roleName)) { $role = $script:RoleOrder[$roleName] }
    $name = [string](Get-Field $Person 'name')
    return '{0}|{1:000000.000}|{2}|{3}' -f $present, $group, $role, $name
}

function Get-Seen($Person) {
    $first = Get-Number (Get-Field $Person 'first')
    $last = Get-Number (Get-Field $Person 'last')
    if ($null -eq $first -or $null -eq $last) { return '' }
    $minutes = [int][Math]::Floor(($last - $first) / 60.0)
    if ($minutes -lt 1) { return '<1m' }
    if ($minutes -lt 60) { return ([string]$minutes + 'm') }
    return ([string][int]($minutes / 60) + 'h ' + [string]($minutes % 60) + 'm')
}

function Format-Report($Session, $StartedAt) {
    if ($null -eq $Session) { return "Ironkeep group`n`nNobody recorded yet." }
    if ($null -eq $StartedAt) {
        $started = Get-Number (Get-Field $Session 'started')
        if ($null -ne $started) {
            $epoch = New-Object DateTime 1970, 1, 1, 0, 0, 0, ([DateTimeKind]::Utc)
            $StartedAt = $epoch.AddSeconds($started).ToLocalTime().ToString('yyyy-MM-dd HH:mm')
        }
        else { $StartedAt = '' }
    }
    $place = [string](Get-Field $Session 'place')
    if ([string]::IsNullOrEmpty($place)) { $place = 'Unknown' }
    $lines = @(
        'Ironkeep group',
        "Place: $place",
        "Started: $StartedAt",
        '',
        'Name | Class | Role | Time | Status'
    )
    $people = @()
    $table = Get-Field $Session 'people'
    if ($table -is [System.Collections.Generic.Dictionary[object,object]]) {
        foreach ($value in $table.Values) {
            if ($value -is [System.Collections.Generic.Dictionary[object,object]]) { $people += $value }
        }
    }
    $people = @($people | Sort-Object { Get-PersonKey $_ })
    foreach ($person in $people) {
        $status = 'left'
        if ((Get-Field $person 'present') -eq $true) { $status = 'here' }
        $name = [string](Get-Field $person 'name')
        if ([string]::IsNullOrEmpty($name)) { $name = 'Unknown' }
        $className = [string](Get-Field $person 'className')
        if ([string]::IsNullOrEmpty($className)) { $className = [string](Get-Field $person 'classFile') }
        $roleName = [string](Get-Field $person 'role')
        $label = ''
        if ($script:RoleLabel.ContainsKey($roleName)) { $label = $script:RoleLabel[$roleName] }
        $lines += (($name, $className, $label, (Get-Seen $person), $status) -join ' | ')
    }
    if ($people.Count -eq 0) { $lines += 'Nobody recorded yet.' }
    $lines += ''
    $lines += 'format: ironkeep-group 1'
    return ($lines -join "`n")
}

function Format-Saved($Db) {
    $session = Get-Field $Db 'session'
    if ($session -is [System.Collections.Generic.Dictionary[object,object]]) {
        return Format-Report $session $null
    }
    $previous = Get-Field $Db 'lastReport'
    if ($previous -is [string] -and $previous.Trim().Length -gt 0) { return $previous }
    return "Ironkeep group`n`nNobody recorded yet."
}

function Get-CompanionSample {
    return @'
-- Shape of the file WoW: Forever writes on logout or /reload.
-- WTF/Account/<account>/SavedVariables/Ironkeep.lua
IronkeepDB = {
	["open"] = true,
	["point"] = "CENTER",
	["x"] = 12.5,
	["y"] = -40,
	["session"] = {
		["place"] = "Hall of Thanes",
		["instanceType"] = "raid",
		["started"] = 1762000000,
		["touched"] = 1762001200,
		["people"] = {
			["Player-5826-0A1"] = {
				["first"] = 1762000000,
				["last"] = 1762001200,
				["present"] = true,
				["name"] = "Ada Smith",
				["classFile"] = "WARRIOR",
				["className"] = "Warrior",
				["role"] = "TANK",
				["subgroup"] = 1,
			},
			["Player-5826-0B2"] = {
				["first"] = 1762000000,
				["last"] = 1762000600,
				["present"] = true,
				["name"] = "Bram Holt",
				["classFile"] = "PRIEST",
				["className"] = "Priest",
				["role"] = "HEALER",
				["subgroup"] = 1,
			},
			["Player-5826-0C3"] = {
				["first"] = 1762000000,
				["last"] = 1762000300,
				["present"] = false,
				["name"] = "Dain Frost",
				["classFile"] = "MAGE",
				["className"] = "Mage",
				["role"] = "DAMAGER",
				["subgroup"] = 2,
			},
		},
	},
}
'@
}

function Get-CompanionUsage {
    return @"
IronkeepCompanion reads the group list saved by the WoW: Forever addon.

  powershell -NoProfile -ExecutionPolicy Bypass -File IronkeepCompanion.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File IronkeepCompanion.ps1 --wow "G:\World of Warcraft\_forever_"
  powershell -NoProfile -ExecutionPolicy Bypass -File IronkeepCompanion.ps1 --sample

With no arguments it looks in G:\World of Warcraft\_forever_ and then C:\World of Warcraft\_forever_.
The addon writes the file when you log out or /reload. Nothing is sent to the site.
"@
}

function Invoke-Companion {
    $sample = $false
    $file = $null
    $wow = $null
    $bare = $null
    for ($i = 0; $i -lt $args.Count; $i++) {
        $arg = [string]$args[$i]
        if ($arg -eq '--sample' -or $arg -eq '-sample') { $sample = $true; continue }
        if ($arg -eq '--file' -or $arg -eq '-file') {
            $i++
            if ($i -ge $args.Count) { [Console]::Error.WriteLine((Get-CompanionUsage)); return 2 }
            $file = [string]$args[$i]
            continue
        }
        if ($arg -eq '--wow' -or $arg -eq '-wow') {
            $i++
            if ($i -ge $args.Count) { [Console]::Error.WriteLine((Get-CompanionUsage)); return 2 }
            $wow = [string]$args[$i]
            continue
        }
        if ($arg.StartsWith('-')) { [Console]::Error.WriteLine((Get-CompanionUsage)); return 2 }
        $bare = $arg
    }

    try {
        if ($sample) {
            $path = 'built-in sample'
            $db = Read-Saved (Get-CompanionSample)
        }
        elseif ($file) {
            $path = $file
            $db = Read-SavedPath $path
        }
        elseif ($wow) {
            $files = @(Get-SavedFiles $wow)
            if ($files.Count -eq 0) { throw "No Ironkeep.lua under $wow. Log out once so the addon can write it." }
            $path = Get-Newest $files
            $account = Get-AccountName $path
            if ($account) { [Console]::Error.WriteLine("Account: $account") }
            $db = Read-SavedPath $path
        }
        elseif ($bare) {
            $path = $bare
            $db = Read-SavedPath $path
        }
        elseif ($args.Count -eq 0) {
            $path = $null
            $db = $null
            foreach ($folder in @('G:\World of Warcraft\_forever_', 'C:\World of Warcraft\_forever_')) {
                $files = @(Get-SavedFiles $folder)
                if ($files.Count -eq 0) { continue }
                $path = Get-Newest $files
                $account = Get-AccountName $path
                if ($account) { [Console]::Error.WriteLine("Account: $account") }
                $db = Read-SavedPath $path
                break
            }
            if ($null -eq $db) { throw 'No Ironkeep.lua yet. Log out of WoW once so the addon can write it.' }
        }
        else {
            [Console]::Error.WriteLine((Get-CompanionUsage))
            return 2
        }
    }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        if ($args.Count -eq 0) {
            [Console]::Error.WriteLine('')
            [Console]::Error.WriteLine((Get-CompanionUsage))
        }
        return 1
    }

    [Console]::Error.WriteLine("Read from: $path")
    [Console]::Out.WriteLine((Format-Saved $db))
    return 0
}

function Get-AccountName([string]$Path) {
    if ([string]::IsNullOrEmpty($Path) -or $Path -eq 'built-in sample') { return '' }
    $saved = [System.IO.Path]::GetDirectoryName($Path)
    $account = [System.IO.Path]::GetDirectoryName($saved)
    return [System.IO.Path]::GetFileName($account)
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-Companion @args)
}
