$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    $nodeVersion = (& node --version).TrimStart("v")
    $nodeMajor = [int]($nodeVersion.Split(".")[0])
    if ($nodeMajor -lt 24) {
        throw "agent-browser 0.27.3 requires Node.js 24 or newer; found $nodeVersion."
    }

    npm ci
    npm exec -- agent-browser install
    npm exec -- agent-browser doctor --offline --quick
    npm exec -- gemini --version
}
finally {
    Pop-Location
}
