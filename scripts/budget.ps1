<#
.SYNOPSIS
    Runner nativo del pipeline budget-gemini para Windows.

.DESCRIPTION
    `make` no existe por defecto en Windows y el Makefile depende de Docker.
    Este script ejecuta el pipeline directamente con Python, sin Docker, y
    fuerza PYTHONUTF8=1 (cp1252 rompia los print con emoji y convertia una
    extraccion exitosa en exit code 1).

.EXAMPLE
    .\scripts\budget.ps1 snapshot
    .\scripts\budget.ps1 snapshot -Days 0
    .\scripts\budget.ps1 reconcile -Plan plan.json
    .\scripts\budget.ps1 ajustar -Cuenta Pibank -InitialBalance 2580398.47 -Delta 2580400.24 -Explicacion "Residual de apertura"
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet(
        'help', 'snapshot', 'analyze', 'learn', 'enrich', 'confirm',
        'dashboard', 'historial', 'reglas', 'pipeline', 'full',
        'reconcile', 'ajustar', 'test'
    )]
    [string]$Command,

    [int]$Days = 90,
    [int]$Limit = 0,
    [string]$Plan,
    [string]$Cuenta,
    [string]$InitialBalance,
    [string]$Delta,
    [string]$Explicacion,
    [switch]$DryRun,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

# --- Raiz del repo (el script vive en scripts/)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# --- Entorno: UTF-8 siempre (bug P2 de cp1252)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = Join-Path $Root 'src'

# --- Python disponible
$Python = $null
foreach ($candidate in @('python', 'py', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source; break }
}
if (-not $Python) {
    Write-Error 'No se encontro Python en PATH. Instala Python 3.11+ o usa Docker.'
    exit 1
}

function Invoke-Step {
    param([string]$Module, [string[]]$Arguments = @())

    Write-Host "`n>> $Module $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Python "-m" $Module @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Fallo en $Module (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# --- Verificar .env
if ($Command -ne 'help') {
    if (-not (Test-Path (Join-Path $Root '.env'))) {
        Write-Error 'Falta .env con WALLET_API_TOKEN (copia .env.example a .env).'
        exit 1
    }
}

switch ($Command) {
    'help' {
        Write-Host @'
Pipeline budget-gemini -- runner nativo (Windows, sin Docker)

  budget.ps1 snapshot   [-Days 90] [-Limit 0]   Extrae datos de Wallet
  budget.ps1 analyze                            Diagnostico con Gemini
  budget.ps1 learn                              Aprende reglas contables
  budget.ps1 enrich                             Enriquece notas/etiquetas
  budget.ps1 confirm                            Confirma reglas (interactivo)
  budget.ps1 dashboard                          Genera dashboard HTML
  budget.ps1 historial                          Historial de snapshots
  budget.ps1 reglas                             Reglas aprendidas
  budget.ps1 pipeline                           snapshot + analyze
  budget.ps1 full                               snapshot + analyze + learn + enrich
  budget.ps1 reconcile -Plan plan.json [-DryRun] [-Yes]
  budget.ps1 ajustar -Cuenta X -InitialBalance N -Delta N -Explicacion "..." [-DryRun]
  budget.ps1 test                               Ejecuta la suite de tests

Notas:
  -Days 0   -> historico completo (NO omite recordDate, usa un piso de fecha)
  -Limit 0  -> sin tope de registros (pagina completo y luego trunca)

Variables de entorno aplicadas automaticamente:
  PYTHONUTF8=1, PYTHONIOENCODING=utf-8, PYTHONPATH=src
'@
    }
    'snapshot' {
        Invoke-Step 'gestor_snapshots' @('--days', "$Days", '--limit', "$Limit")
    }
    'analyze' {
        Invoke-Step 'analizador_finanzas'
    }
    'learn' {
        Invoke-Step 'aprendizaje_reglas'
    }
    'enrich' {
        Invoke-Step 'asistente_enriquecimiento' @('--auto')
    }
    'confirm' {
        Invoke-Step 'confirmador_reglas'
    }
    'dashboard' {
        Invoke-Step 'generar_dashboard'
    }
    'historial' {
        Invoke-Step 'gestor_snapshots' @('--historial')
    }
    'reglas' {
        Invoke-Step 'aprendizaje_reglas' @('--mostrar-reglas')
    }
    'pipeline' {
        Invoke-Step 'run_pipeline'
    }
    'full' {
        Invoke-Step 'run_pipeline' @('--full')
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
