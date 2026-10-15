param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$cubeReleaseRoot = (Resolve-Path -LiteralPath $Root).Path
$cubeCompiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $cubeCompiler)) { throw 'Windows .NET Framework C# compiler is unavailable.' }
$cubeOutput = Join-Path $cubeReleaseRoot '启动Cube助手.exe'
$cubeArguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/debug-',
    ('/win32icon:' + (Join-Path $cubeReleaseRoot 'cube_ai/web/cube-icon.ico')),
    ('/out:' + $cubeOutput), '/reference:System.dll', '/reference:System.Windows.Forms.dll',
    (Join-Path $cubeReleaseRoot '入口源码/PortableBootstrap.cs'))
& $cubeCompiler @cubeArguments
if ($LASTEXITCODE -ne 0) { throw 'Portable entrance compilation failed.' }
Copy-Item -LiteralPath $cubeOutput -Destination (Join-Path $cubeReleaseRoot '关闭Cube助手.exe')
Write-Output 'Portable entrances compiled.'
