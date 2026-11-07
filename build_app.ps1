param(
    # 默认使用仓库内的独立虚拟环境；可显式指向其他兼容解释器。
    [string]$PythonExecutable,
    [string]$OutputDirectory,
    [switch]$Force
)
# 只构建本仓库的窗口版程序。dist 与 build 由 .gitignore 排除，不进入版本库。
$ErrorActionPreference = 'Stop'
$ApplicationRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PythonExecutable) { $PythonExecutable = Join-Path $ApplicationRoot '.venv\Scripts\python.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $ApplicationRoot 'dist' }
$OutputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$WorkRoot = [IO.Path]::GetFullPath((Join-Path $ApplicationRoot 'build'))

# 删除前核对绝对路径：只允许重建仓库自己的 dist 与 build 目录。
$Allowed = @([IO.Path]::GetFullPath((Join-Path $ApplicationRoot 'dist')), $WorkRoot)
if ($Allowed -notcontains $OutputRoot) { throw "为安全起见只允许构建到仓库内 dist：$OutputRoot" }
if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw "Python解释器不存在：$PythonExecutable" }
if (Test-Path -LiteralPath $OutputRoot) {
    if (-not $Force) { throw "输出目录已存在；确认要重建请加 -Force：$OutputRoot" }
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
if (Test-Path -LiteralPath $WorkRoot) { Remove-Item -LiteralPath $WorkRoot -Recurse -Force }
$TemporaryRoot = Join-Path $WorkRoot 'temp'
New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
$PreviousTemp = $env:TEMP
$PreviousTmp = $env:TMP
$PreviousPath = $env:PATH
try {
    $env:TEMP = $TemporaryRoot
    $env:TMP = $TemporaryRoot
    # 只向构建器提供Python与Windows路径，避免收集到其他工具的同名不兼容DLL。
    $BasePython = (& $PythonExecutable -c "import sys; print(sys.base_prefix)").Trim()
    if ($LASTEXITCODE -ne 0) { throw '读取Python基础环境失败。' }
    $env:PATH = @((Split-Path -Parent $PythonExecutable), $BasePython, (Join-Path $BasePython 'DLLs'),
                  (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    # PowerShell 5.1 在 Stop 模式下会把原生命令的 stderr 当成终止错误，
    # 因此构建期间临时放宽，改由 $LASTEXITCODE 判断成败。
    $BuildErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $PythonExecutable -m PyInstaller --clean --noconfirm `
        --distpath $OutputRoot --workpath (Join-Path $WorkRoot 'pyinstaller') `
        (Join-Path $ApplicationRoot 'WindTrace.spec') 2>&1 |
        Tee-Object -FilePath (Join-Path $WorkRoot 'build.log')
    $BuildExitCode = $LASTEXITCODE
    $ErrorActionPreference = $BuildErrorAction
    if ($BuildExitCode -ne 0) { throw 'PyInstaller构建失败；构建日志保留在 build\build.log。' }
    $Program = Join-Path $OutputRoot 'WindTrace\WindTrace.exe'
    if (-not (Test-Path -LiteralPath $Program)) { throw '未生成可执行文件。' }
    Write-Output "已构建：$Program"
} finally {
    $env:TEMP = $PreviousTemp
    $env:TMP = $PreviousTmp
    $env:PATH = $PreviousPath
}
