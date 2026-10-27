<#
.SYNOPSIS
    Runner nativo del proyecto Wallet (Windows, sin Docker, sin make).

.DESCRIPTION
    Ejecuta las herramientas deterministas de tools/ y fuerza UTF-8.
    El uso diario va por el MCP de Wallet dentro del agente; este runner es
    para respaldo, generacion de la Knowledge Base, conciliacion y ajustes.

    En Windows, `make` no viene instalado por defecto y el Makefile depende de
    Docker. Este script ejecuta Python directamente.

    PYTHONUTF8=1 es obligatorio: con cp1252 un print() con acentos revienta y
    una extraccion exitosa termina con exit code 1.

.EXAMPLE
    .\scripts\budget.ps1 doctor
    .\scripts\budget.ps1 backup
    .\scripts\budget.ps1 bootstrap
    .\scripts\budget.ps1 reconcile -Plan plans\plan_pibank.json -DryRun
    .\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2.580.398,47 -Delta 2.580.400,24 -Explicacion "Residual de apertura"
    .\scripts\budget.ps1 test
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('help', 'doctor', 'backup', 'bootstrap', 'reconcile', 'ajustar', 'test')]
    [string]$Command,

    [int]$Days = 0,
    [string]$Plan,
    [string]$Cuenta,
    [string]$InitialBalance,
    [string]$Delta,
    [string]$Explicacion,
    [string]$Out,
    [switch]$DryRun,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

# --- Raiz del repo (este script vive en scripts/) ---------------------------
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# --- Entorno UTF-8 + tools en el path ---------------------------------------
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = Join-Path $Root 'tools'

$Python = $null
foreach ($candidate in @('python', 'py', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source; break }
}
if (-not $Python) {
    Write-Error 'No se encontro Python en PATH. Instala Python 3.11+'
    exit 1
}

function Invoke-Step {
    param([string]$Module, [string[]]$Arguments = @())
    Write-Host "`n>> $Module $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Python (Join-Path $Root "tools\$Module.py") @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Fallo en $Module (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Command -notin @('help', 'doctor', 'test')) {
    if (-not (Test-Path (Join-Path $Root '.env'))) {
        Write-Error 'Falta .env con WALLET_API_TOKEN (copia .env.example a .env).'
        exit 1
    }
}

switch ($Command) {
    'help' {
        Write-Host @'
Wallet + Knowledge Base -- runner nativo (Windows, sin Docker)

  budget.ps1 doctor                          Comprueba entorno y KB
  budget.ps1 backup [-Out ruta.json]         Respaldo completo a JSON
  budget.ps1 bootstrap [-Days 0] [-DryRun]   (Re)genera rules/*.md desde el historico
  budget.ps1 reconcile -Plan plan.json [-DryRun] [-Yes]
                                             Concilia una cuenta contra una captura
  budget.ps1 ajustar -Cuenta X -InitialBalance N -Delta N -Explicacion "..." [-DryRun]
                                             Ajuste de partida de apertura
  budget.ps1 test                            Suite de tests

Notas:
  -Days 0   -> historico completo (siempre se manda recordDate explicito)
  -DryRun   -> muestra el resultado, no escribe en Wallet
  -Yes      -> si el plan ya fue aprobado por el humano, no vuelve a preguntar

El uso diario (registrar, consultar, informes) se hace por el MCP de Wallet
dentro del agente, no por este script.
'@
    }
    'doctor' {
        Write-Host "Raiz            : $Root"
        Write-Host "Python          : $Python"
        & $Python '--version'
        Write-Host (".env            : " + $(if (Test-Path (Join-Path $Root '.env')) { 'presente' } else { 'FALTA' }))
        Write-Host (".opencode/      : " + $(if (Test-Path (Join-Path $Root '.opencode')) { 'presente' } else { 'FALTA' }))
        $mcp = Join-Path $Root 'opencode.json'
        if (Test-Path $mcp) {
            $cfg = Get-Content $mcp -Raw | ConvertFrom-Json
            $servidores = @($cfg.mcp.servers.PSObject.Properties.Name)
            Write-Host ("MCP en config   : " + ($(if ($servidores.Count) { $servidores -join ', ' } else { 'ninguno' })))
        } else {
            Write-Host 'MCP en config   : FALTA opencode.json'
        }
        foreach ($archivo in @('cuentas.md', 'categorias.md', 'etiquetas.md', 'informes.md', 'mcp_tools.md')) {
            $ruta = Join-Path $Root "rules\$archivo"
            Write-Host ("rules\$archivo : " + $(if (Test-Path $ruta) { 'ok' } else { 'FALTA' }))
        }
    }
    'backup' {
        $a = @()
        if ($Out) { $a += @('--out', $Out) }
        Invoke-Step 'backup_wallet' $a
    }
    'bootstrap' {
        $a = @('--days', "$Days")
        if ($DryRun) { $a += '--dry-run' }
        Invoke-Step 'bootstrap_rules' $a
    }
    'reconcile' {
        if (-not $Plan) { Write-Error 'Uso: budget.ps1 reconcile -Plan plan.json'; exit 1 }
        $a = @('--plan', $Plan)
        if ($DryRun) { $a += '--dry-run' }
        if ($Yes) { $a += '--yes' }
        Invoke-Step 'conciliar_cuenta' $a
    }
    'ajustar' {
        if (-not $Cuenta -or -not $InitialBalance) {
            Write-Error 'Uso: budget.ps1 ajustar -Cuenta X -InitialBalance N -Delta N -Explicacion "..."'
            exit 1
        }
        $a = @('--cuenta', $Cuenta, '--initial-balance', "$InitialBalance")
        if ($Delta) { $a += @('--delta', $Delta) }
        if ($Explicacion) { $a += @('--explicacion', $Explicacion) }
        if ($DryRun) { $a += '--dry-run' }
        Invoke-Step 'ajustar_saldo_cuenta' $a
    }
    'test' {
        & $Python '-m' 'pytest' 'tests' '-q'
        exit $LASTEXITCODE
    }
}
