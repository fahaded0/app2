[CmdletBinding()]
param(
    [Parameter()]
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "secrets"),

    [Parameter()]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-SecureRandomBytes {
    param(
        [Parameter(Mandatory)]
        [ValidateRange(16, 1024)]
        [int]$Count
    )

    [byte[]]$bytes =
        New-Object byte[] $Count

    $generator =
        [System.Security.Cryptography.RandomNumberGenerator]::Create()

    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }

    return $bytes
}

function ConvertTo-Base64Url {
    param(
        [Parameter(Mandatory)]
        [byte[]]$Bytes
    )

    return (
        [Convert]::ToBase64String($Bytes).
            TrimEnd("=").
            Replace("+", "-").
            Replace("/", "_")
    )
}

function Write-AsciiSecret {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Refusing to write an empty secret: $Path"
    }

    if ($Value -match "[`r`n]") {
        throw "Secret values must not contain line breaks: $Path"
    }

    [System.IO.File]::WriteAllText(
        $Path,
        $Value,
        [System.Text.Encoding]::ASCII
    )
}

$resolvedOutput =
    [System.IO.Path]::GetFullPath($OutputDirectory)

$expectedNames = @(
    "mongo-root-username.key",
    "mongo-root-password.key",
    "mongo-app-username.key",
    "mongo-app-password.key",
    "mongo-keyfile.key"
)

[System.IO.Directory]::CreateDirectory(
    $resolvedOutput
) | Out-Null

[string[]]$existingExpectedFiles = @(
    foreach ($name in $expectedNames) {
        $candidate =
            Join-Path $resolvedOutput $name

        if (
            Test-Path `
                -LiteralPath $candidate `
                -PathType Leaf
        ) {
            $candidate
        }
    }
)

if (
    $existingExpectedFiles.Count -ne 0 -and
    -not $Force
) {
    throw (
        "One or more MongoDB secret files already exist. " +
        "No file was overwritten. Use -Force only for a disposable, " +
        "empty-volume environment."
    )
}

if ($Force) {
    foreach ($path in $existingExpectedFiles) {
        Remove-Item `
            -LiteralPath $path `
            -Force
    }
}

$rootUsername =
    "app2_root"

$appUsername =
    "medstock_app"

$rootPassword =
    ConvertTo-Base64Url `
        -Bytes (
            New-SecureRandomBytes `
                -Count 48
        )

$appPassword =
    ConvertTo-Base64Url `
        -Bytes (
            New-SecureRandomBytes `
                -Count 48
        )

$replicaSetKey =
    [Convert]::ToBase64String(
        (
            New-SecureRandomBytes `
                -Count 96
        )
    )

$secretValues =
    [ordered]@{
        "mongo-root-username.key" = $rootUsername
        "mongo-root-password.key" = $rootPassword
        "mongo-app-username.key"   = $appUsername
        "mongo-app-password.key"   = $appPassword
        "mongo-keyfile.key"        = $replicaSetKey
    }

foreach ($entry in $secretValues.GetEnumerator()) {
    $path =
        Join-Path `
            $resolvedOutput `
            $entry.Key

    Write-AsciiSecret `
        -Path $path `
        -Value $entry.Value
}

if ($rootUsername -notmatch "^[A-Za-z][A-Za-z0-9_.-]{2,63}$") {
    throw "Generated root username is invalid."
}

if ($appUsername -ne "medstock_app") {
    throw "Generated application username is not medstock_app."
}

if (
    $rootPassword.Length -lt 48 -or
    $rootPassword -notmatch "^[A-Za-z0-9_-]+$"
) {
    throw "Generated root password failed validation."
}

if (
    $appPassword.Length -lt 48 -or
    $appPassword -notmatch "^[A-Za-z0-9_-]+$"
) {
    throw "Generated application password failed validation."
}

if (
    $replicaSetKey.Length -lt 6 -or
    $replicaSetKey.Length -gt 1024 -or
    $replicaSetKey -notmatch "^[A-Za-z0-9+/=]+$"
) {
    throw "Generated replica-set keyfile failed validation."
}

if ($env:OS -ne "Windows_NT") {
    foreach ($name in $expectedNames) {
        $path =
            Join-Path $resolvedOutput $name

        & chmod `
            600 `
            -- `
            $path

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to set Unix permissions on $path."
        }
    }
}

$gitCommand =
    Get-Command `
        git `
        -ErrorAction SilentlyContinue

if ($null -ne $gitCommand) {
    $oldPreference =
        $ErrorActionPreference

    try {
        $ErrorActionPreference =
            "Continue"

        $repoRoot =
            (
                & git `
                    -C `
                    $PSScriptRoot `
                    rev-parse `
                    --show-toplevel `
                    2>$null |
                Out-String
            ).Trim()

        $repoExit =
            $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference =
            $oldPreference
    }

    if (
        $repoExit -eq 0 -and
        -not [string]::IsNullOrWhiteSpace($repoRoot)
    ) {
        $repoFull =
            [System.IO.Path]::GetFullPath($repoRoot).
                TrimEnd(
                    [System.IO.Path]::DirectorySeparatorChar,
                    [System.IO.Path]::AltDirectorySeparatorChar
                )

        foreach ($name in $expectedNames) {
            $path =
                [System.IO.Path]::GetFullPath(
                    (
                        Join-Path `
                            $resolvedOutput `
                            $name
                    )
                )

            if (
                $path.StartsWith(
                    $repoFull,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            ) {
                Push-Location $repoFull

                try {
                    $relativePath =
                        Resolve-Path `
                            -LiteralPath $path `
                            -Relative

                    $oldPreference =
                        $ErrorActionPreference

                    try {
                        $ErrorActionPreference =
                            "Continue"

                        & git check-ignore `
                            --quiet `
                            --no-index `
                            -- `
                            $relativePath

                        $ignoreExit =
                            $LASTEXITCODE
                    }
                    finally {
                        $ErrorActionPreference =
                            $oldPreference
                    }

                    if ($ignoreExit -ne 0) {
                        throw (
                            "Generated secret file is not protected by " +
                            ".gitignore: $relativePath"
                        )
                    }
                }
                finally {
                    Pop-Location
                }
            }
        }
    }
}

Write-Host "MongoDB production secret files prepared."
Write-Host "Output directory: $resolvedOutput"
Write-Host "Files created: $($expectedNames.Count)"

foreach ($name in $expectedNames) {
    Write-Host $name
}

Write-Host (
    "Secret values were not printed. " +
    "Do not commit or transmit the generated files."
)
