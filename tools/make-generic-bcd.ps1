<#
Builds a generic Windows boot configuration (BCD) for mck-pxe WIM deployments.

Run once, as Administrator, on any Windows 10/11 PC, then upload the BCD file it
creates on the mck-pxe Settings page.

bcdboot normally writes a BCD pointing at one specific disk and partition.
This one uses "locate", so Windows Boot Manager finds \Windows on whatever
disk mck-pxe deployed to.
#>
param([string]$Locale = "en-US")
$ErrorActionPreference = "Stop"

$bcd = Join-Path (Get-Location) "BCD"
if (Test-Path $bcd) { Remove-Item $bcd }

function Run([string[]]$Arguments) {
    $out = & bcdedit.exe /store $bcd @Arguments
    if ($LASTEXITCODE -ne 0) { throw "bcdedit $Arguments failed: $out" }
    return $out
}

& bcdedit.exe /createstore $bcd | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create $bcd (run as Administrator)" }

Run @("/create", "{bootmgr}", "/d", "Windows Boot Manager") | Out-Null
Run @("/set", "{bootmgr}", "device", "boot") | Out-Null
Run @("/set", "{bootmgr}", "locale", $Locale) | Out-Null
Run @("/set", "{bootmgr}", "timeout", "0") | Out-Null

$created = Run @("/create", "/d", "Windows", "/application", "osloader")
$guid = [regex]::Match(($created -join " "), "\{[0-9a-fA-F-]{36}\}").Value
if (-not $guid) { throw "Could not read the new loader's id from: $created" }

Run @("/set", $guid, "device", "locate=\Windows\system32\winload.efi") | Out-Null
Run @("/set", $guid, "osdevice", "locate=\Windows") | Out-Null
Run @("/set", $guid, "path", "\Windows\system32\winload.efi") | Out-Null
Run @("/set", $guid, "systemroot", "\Windows") | Out-Null
Run @("/set", $guid, "locale", $Locale) | Out-Null
Run @("/set", $guid, "nx", "OptIn") | Out-Null
Run @("/set", $guid, "bootmenupolicy", "Standard") | Out-Null

Run @("/set", "{bootmgr}", "default", $guid) | Out-Null
Run @("/set", "{bootmgr}", "displayorder", $guid) | Out-Null

Write-Host "Created $bcd"
& bcdedit.exe /store $bcd /enum all
