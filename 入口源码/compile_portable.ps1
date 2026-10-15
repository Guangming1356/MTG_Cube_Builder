param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$cubeReleaseRoot = (Resolve-Path -LiteralPath $Root).Path
$cubeSource = [System.IO.File]::ReadAllText((Join-Path $cubeReleaseRoot '入口源码\PortableBootstrap.cs'), [System.Text.Encoding]::UTF8)
$cubeCompiler = New-Object Microsoft.CSharp.CSharpCodeProvider
$cubeParameters = New-Object System.CodeDom.Compiler.CompilerParameters
$cubeParameters.GenerateExecutable = $true
$cubeParameters.GenerateInMemory = $false
$cubeParameters.IncludeDebugInformation = $false
$cubeParameters.OutputAssembly = Join-Path $cubeReleaseRoot '启动Cube助手.exe'
$cubeIcon = Join-Path $cubeReleaseRoot 'cube_ai\web\cube-icon.ico'
$cubeParameters.CompilerOptions = '/target:winexe /platform:x64 /optimize+ /debug- /win32icon:"' + $cubeIcon + '"'
[void]$cubeParameters.ReferencedAssemblies.Add('System.dll')
[void]$cubeParameters.ReferencedAssemblies.Add('System.Windows.Forms.dll')
$cubeResult = $cubeCompiler.CompileAssemblyFromSource($cubeParameters, [string[]]@($cubeSource))
if ($cubeResult.Errors.HasErrors) { throw ($cubeResult.Errors | Out-String) }
Copy-Item -LiteralPath $cubeParameters.OutputAssembly -Destination (Join-Path $cubeReleaseRoot '关闭Cube助手.exe')
Write-Output 'Portable entrances compiled.'
