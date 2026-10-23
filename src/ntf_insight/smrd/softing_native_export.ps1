# Offline, read-only SMR-D metadata browser via the user's licensed
# Softing DTS managed API. No vehicle connection and no ECU service execution.
# Available native exports checked against the user's CSWrap.dll. The
# dynamic-project opening sequence still requires Windows runtime validation.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $RuntimeDir,
    [string] $SmrdFile = '',
    [string] $OutputJson = '',
    [switch] $ProbeOnly,
    [ValidateRange(1, 250000)][int] $MaxDtcs = 250000
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ([IntPtr]::Size -ne 8) { throw 'Softing DTS requires 64-bit Windows.' }
$runtime = (Resolve-Path -LiteralPath $RuntimeDir -ErrorAction Stop).Path
$bin = if (Test-Path -LiteralPath (Join-Path $runtime 'mvci\bin\Softing.Dts.dll')) {
    Join-Path $runtime 'mvci\bin'
} elseif (Test-Path -LiteralPath (Join-Path $runtime 'bin\Softing.Dts.dll')) {
    Join-Path $runtime 'bin'
} else { $runtime }
$dll = Join-Path $bin 'Softing.Dts.dll'
if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
    throw "Softing.Dts.dll not found: $dll"
}
if (-not $ProbeOnly) {
    if (-not $SmrdFile -or -not $OutputJson) {
        throw 'SmrdFile and OutputJson are required.'
    }
    $SmrdFile = (Resolve-Path -LiteralPath $SmrdFile -ErrorAction Stop).Path
    if ([IO.Path]::GetExtension($SmrdFile).ToLowerInvariant() -ne '.smr-d') {
        throw 'Only .smr-d input files are allowed.'
    }
    $OutputJson = [IO.Path]::GetFullPath($OutputJson)
}

function Read-Prop($obj, [string] $name) {
    if ($null -eq $obj) { return $null }
    $property = $obj.GetType().GetProperty($name)
    if ($null -eq $property) { return $null }
    return $property.GetValue($obj, $null)
}
function Read-Text($obj, [string] $name) {
    $value = Read-Prop $obj $name
    if ($null -eq $value) { return '' }
    return [string] $value
}
function Read-Items($collection) {
    if ($null -eq $collection) { return }
    $count = [int] (Read-Prop $collection 'Count')
    if ($count -lt 0 -or $count -gt 250000) {
        throw "Unexpected DTS collection count: $count"
    }
    for ($i = 0; $i -lt $count; $i++) {
        $item = $collection.GetItemByIndex([int] $i)
        if ($null -ne $item) { Write-Output -NoEnumerate $item }
    }
}
function Read-Sdgs($dtc) {
    $answer = New-Object 'System.Collections.Generic.List[object]'
    foreach ($group in @(Read-Items (Read-Prop $dtc 'DbSDGs'))) {
        if ($null -eq $group) { continue }
        $elements = New-Object 'System.Collections.Generic.List[object]'
        foreach ($element in @(Read-Items $group)) {
            if ($null -eq $element) { continue }
            $elements.Add(@{
                semantic = Read-Text $element 'SemanticInformation'
                content = Read-Text $element 'Content'
                text_id = Read-Text $element 'TextID'
            })
        }
        $caption = ''
        if ([bool] (Read-Prop $group 'HasCaption')) {
            $cap = Read-Prop $group 'Caption'
            $caption = Read-Text $cap 'LongName'
            if (-not $caption) { $caption = Read-Text $cap 'ShortName' }
        }
        $answer.Add(@{
            semantic = Read-Text $group 'SemanticInformation'
            caption = $caption
            elements = @($elements.ToArray())
        })
    }
    return $answer.ToArray()
}

$oldPath = $env:Path
$env:Path = "$bin;$oldPath"
$system = $null
$dbProject = $null
$project = $null
$selected = $false
$initialized = $false
Push-Location -LiteralPath $runtime
try {
    Add-Type -Path $dll -ErrorAction Stop
    if ($ProbeOnly) {
        $systemType = [Softing.Dts.DtsSystem]
        foreach ($name in @('Initialize', 'SelectDynamicProject', 'DeselectProject')) {
            if (-not ($systemType.GetMethod($name))) {
                throw "DTS runtime incompatible; missing method: $name"
            }
        }
        if (-not ([Softing.Dts.DtsProject].GetProperty('DbProject'))) {
            throw 'Dynamic DTS project has no DbProject property.'
        }
        if (-not ([Softing.Dts.Statics].GetMethod('getSystem'))) {
            throw 'DTS factory method getSystem is missing.'
        }
        Write-Output (
            'SOFTING_DTS_MANAGED_API_OK ' +
            [Softing.Dts.Statics].Assembly.GetName().Version.ToString()
        )
    } else {
        # Offline database API only: never call GotoOnline or diagnostic services.
        $system = [Softing.Dts.Statics]::getSystem()
        if ($null -eq $system) { throw 'DTS system factory returned null.' }
        $system.Initialize()
        $initialized = $true
        # The managed LoadViewerProject method has no matching export in
        # this vendor's CSWrap.dll. SelectDynamicProject has a native export
        # and accepts an ECU-independent array of offline SMR-D files.
        $project = $system.SelectDynamicProject(
            'NTFInsight_Offline', [string[]] @($SmrdFile)
        )
        if ($null -eq $project) { throw 'SelectDynamicProject returned null.' }
        $selected = $true
        $dbProject = Read-Prop $project 'DbProject'
        if ($null -eq $dbProject) { throw 'DtsProject.DbProject returned null.' }

        $found = New-Object 'System.Collections.Generic.List[object]'
        $seen = New-Object 'System.Collections.Generic.HashSet[string]'
        $errors = New-Object 'System.Collections.Generic.List[string]'
        $variantCount = 0
        $locationCount = 0
        $allVariants = New-Object 'System.Collections.Generic.List[object]'

        foreach ($mem in @(Read-Items (Read-Prop $dbProject 'DbEcuMems'))) {
            if ($null -eq $mem) { continue }
            $ecuName = Read-Text $mem 'ShortName'
            foreach ($collectionName in @('Variants', 'BaseVariants')) {
                foreach ($v in @(Read-Items (Read-Prop $mem $collectionName))) {
                    if ($null -ne $v) {
                        $allVariants.Add(@{ ecu = $ecuName; variant = $v })
                    }
                }
            }
        }
        if ($allVariants.Count -eq 0) {
            foreach ($v in @(Read-Items (Read-Prop $dbProject 'DbEcuBaseVariants'))) {
                if ($null -ne $v) {
                    $allVariants.Add(@{ ecu = ''; variant = $v })
                }
            }
        }
        if ($allVariants.Count -eq 0) {
            throw 'No ECU variants found in the offline DTS database.'
        }

        foreach ($item in $allVariants) {
            $variant = $item.variant
            $variantName = Read-Text $variant 'ShortName'
            if (-not $variantName) { continue }
            $variantCount++
            foreach ($location in @(Read-Items (Read-Prop $variant 'DbLocations'))) {
                if ($null -eq $location) { continue }
                $locationCount++
                $locationName = Read-Text $location 'ShortName'
                $dbEcu = Read-Prop $location 'DbECU'
                $ecuName = $item.ecu
                if (-not $ecuName) { $ecuName = Read-Text $dbEcu 'ShortName' }
                if (-not $ecuName) {
                    $ecuName = [IO.Path]::GetFileNameWithoutExtension($SmrdFile)
                }

                $dtcList = $null
                $directFailed = $null
                try {
                    $dtcList = $location.GetDbDTCs($true, $true)
                } catch {
                    $directFailed = $_.Exception.Message
                }
                $dtcs = @()
                if ($null -ne $dtcList) { $dtcs = @(Read-Items $dtcList) }
                if ($dtcs.Count -eq 0) {
                    try {
                        foreach ($fm in @(Read-Items (Read-Prop $location 'DbFaultMemories'))) {
                            if ($null -eq $fm) { continue }
                            $dtcs += @(Read-Items ($fm.GetDbDiagTroubleCodes($true, $true)))
                        }
                        $directFailed = $null
                    } catch {
                        $errors.Add(
                            "DTCs ${variantName}/${locationName}: " + $_.Exception.Message
                        )
                    }
                }
                if ($null -ne $directFailed) {
                    $errors.Add("DTCs ${variantName}/${locationName}: $directFailed")
                }

                foreach ($dtc in $dtcs) {
                    if ($null -eq $dtc) { continue }
                    try {
                        $code = Read-Text $dtc 'DisplayTroubleCode'
                        if (-not $code) { $code = Read-Text $dtc 'ShortName' }
                        if (-not $code) { continue }
                        $key = "$ecuName|$variantName|$locationName|$code"
                        if (-not $seen.Add($key)) { continue }
                        $dtcText = Read-Text $dtc 'UnicodeDTCText'
                        if (-not $dtcText) { $dtcText = Read-Text $dtc 'DTCText' }
                        if ($found.Count -ge $MaxDtcs) {
                            throw 'Maximum DTC count exceeded.'
                        }
                        $found.Add(@{
                            ecu = $ecuName
                            variant = $variantName
                            location = $locationName
                            code = $code
                            trouble_code = Read-Prop $dtc 'TroubleCode'
                            dtc_text = $dtcText
                            level = Read-Prop $dtc 'Level'
                            short_name = Read-Text $dtc 'ShortName'
                            sdgs = @(Read-Sdgs $dtc)
                        })
                    } catch {
                        $errors.Add(
                            "DTC ${variantName}/${locationName}/${code}: " +
                            $_.Exception.Message
                        )
                    }
                }
            }
        }
        if ($found.Count -eq 0) {
            throw 'DTS returned no DTCs. No database will be modified.'
        }
        $hash = (Get-FileHash -LiteralPath $SmrdFile -Algorithm SHA256).Hash.ToLowerInvariant()
        $data = @{
            format = 'ntf-smrd-native-dtc-v1'
            smrd_sha256 = $hash
            smrd_filename = [IO.Path]::GetFileName($SmrdFile)
            dts_version = [Softing.Dts.Statics].Assembly.GetName().Version.ToString()
            complete = ($errors.Count -eq 0)
            variant_count = $variantCount
            location_count = $locationCount
            dtcs = @($found.ToArray())
            warnings = @($errors.ToArray())
        }
        $json = ConvertTo-Json -InputObject $data -Depth 15 -Compress
        [IO.File]::WriteAllText(
            $OutputJson, $json, (New-Object System.Text.UTF8Encoding($false))
        )
        if ($errors.Count) {
            throw (
                'DTS traversal incomplete: ' + $errors.Count +
                ' error(s). Temporary output is discarded; no import.'
            )
        }
        Write-Output ("SOFTING_DTS_DTC_EXPORT_OK count={0}" -f $found.Count)
    }
} finally {
    if ($selected -and $null -ne $system) {
        try { $system.DeselectProject() } catch { }
    }
    if ($initialized -and $null -ne $system) {
        try { $system.Uninitialize() } catch { }
    }
    Pop-Location
    $env:Path = $oldPath
}
