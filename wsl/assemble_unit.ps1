# Assemble a compile-input blob exactly as build/compile.ps1 does:
# mode header + cited chapters + source + EOT. Reuses the repo's own
# quire-map.ps1 for cite resolution.
param(
    [Parameter(Mandatory=$true)] [string]$Src,
    [Parameter(Mandatory=$true)] [string]$OutBlob,
    [string]$Mode = 'CDX'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location '/home/steve/showell_repos/NewRepository'
[System.Environment]::CurrentDirectory = '/home/steve/showell_repos/NewRepository'
. build/quire-map.ps1

$srcLines = [System.IO.File]::ReadAllLines($Src)
$seedSeen = @{}
foreach ($line in $srcLines) {
    if ($line -match '^Chapter:\s*(\w+)--(.+?)\s*$') { $seedSeen["$($matches[1])::$($matches[2])"] = $true }
}
$ordered = Resolve-CiteOrder -RootLines $srcLines -Repo '.' -SeedSeen $seedSeen
Write-Host "chapters resolved: $(@($ordered).Count)"
foreach ($o in $ordered) { Write-Host "  $($o.Quire)::$($o.Name)" }

$sb = [System.Text.StringBuilder]::new(524288)
[void]$sb.Append("$Mode`n")
foreach ($l in (Format-CiteChapters -Ordered $ordered)) { [void]$sb.Append($l + "`n") }
foreach ($line in $srcLines) { [void]$sb.Append($line + "`n") }
[void]$sb.Append([char]4)
[System.IO.File]::WriteAllText($OutBlob, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
Write-Host "blob: $((Get-Item $OutBlob).Length) bytes -> $OutBlob"
