# Opt-in acceptance on an authorized Hyper-V HOST with a disposable Windows VM.
# This does not run on GitHub-hosted Actions: no nested Hyper-V VM is available.
# Stop-VM -TurnOff drops VIRTUAL power, not physical electricity.
# Requires guest Windows, PowerShell Direct support, Python 3.11+ and Git.
# Only operates on a freshly created fixture; no user's project is touched.
param(
    [Parameter(Mandatory=$true)][string]$VMName,
    [Parameter(Mandatory=$true)][System.Management.Automation.PSCredential]$Credential,
    [Parameter(Mandatory=$true)][switch]$IUnderstandVirtualPowerCut,
    [string[]]$Phases = @('after_backup','after_worktree','after_branch','after_patch','after_staged'),
    [string]$ReceiptPath = "$PWD\vm-powercut-proof.json"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $IUnderstandVirtualPowerCut) { throw "Explicit virtual power cut authorization required" }
if ($VMName -cnotmatch '^JARVIS-DISPOSABLE-[A-Za-z0-9-]{3,64}$') {
    throw "Refusing to power off a non-disposable VM; requires JARVIS-DISPOSABLE-*"
}
$allowed = @('after_backup','after_worktree','after_branch','after_patch','after_staged')
foreach ($phase in $Phases) {
    if ($phase -cnotin $allowed) { throw "Unsupported power-cut phase" }
}
if (-not (Get-Command -Name Stop-VM -ErrorAction SilentlyContinue) -or
    -not (Get-Command -Name New-PSSession -ErrorAction SilentlyContinue)) {
    throw "A real authorized Windows Hyper-V host with PowerShell Direct is required"
}
$vm = Get-VM -Name $VMName -ErrorAction Stop
if ($vm.Name -cne $VMName -or $vm.State.ToString() -ne 'Running') {
    throw "The named disposable VM must exist and already be running"
}
$vmId = $vm.Id.ToString()
$toolsDir = Join-Path $PSScriptRoot '..'
$backend = Join-Path $toolsDir 'jarvis-studio-backend'
$files = @(
    (Join-Path $PSScriptRoot 'powerloss-guest-fixture.py'),
    (Join-Path $backend 'authorized_git_transaction.py'),
    (Join-Path $backend 'durable_git_recovery.py')
)
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing trusted test fixture: $file"
    }
}
$results = @()
$allPass = $false
$session = $null
try {
    foreach ($phase in $Phases) {
        $runId = [Guid]::NewGuid().ToString('N')
        $guestTools = "C:\JARVIS-POWERTOOLS-$runId"
        $guestWorkspace = "C:\JARVIS-POWERLAB-$runId"
        $session = New-PSSession -VMName $VMName -Credential $Credential -ErrorAction Stop
        try {
            Invoke-Command -Session $session -ScriptBlock {
                param($dest)
                New-Item -Path $dest -ItemType Directory -Force | Out-Null
                & python --version
                if ($LASTEXITCODE -ne 0) { throw 'Python unavailable in disposable Windows VM' }
                & git --version
                if ($LASTEXITCODE -ne 0) { throw 'Git unavailable in disposable Windows VM' }
            } -ArgumentList $guestTools
            foreach ($file in $files) {
                Copy-Item -LiteralPath $file -Destination $guestTools -ToSession $session -ErrorAction Stop
            }
            Invoke-Command -Session $session -ScriptBlock {
                param($tools, $folder)
                & python (Join-Path $tools 'powerloss-guest-fixture.py') init --workspace $folder
                if ($LASTEXITCODE -ne 0) { throw 'Synthetic clean Git fixture init failed' }
            } -ArgumentList $guestTools,$guestWorkspace

            Invoke-Command -Session $session -ScriptBlock {
                param($tools, $folder, $cutPhase)
                $fixture = Join-Path $tools 'powerloss-guest-fixture.py'
                $p = Start-Process -FilePath 'python.exe' -ArgumentList @(
                    $fixture, 'stage', '--workspace', $folder, '--phase', $cutPhase
                ) -WorkingDirectory $tools -WindowStyle Hidden -PassThru
                if ($p.HasExited) { throw 'Guest transaction terminated prematurely' }
            } -ArgumentList $guestTools,$guestWorkspace,$phase

            $ready = $false
            $deadline = (Get-Date).AddSeconds(90)
            while ((Get-Date) -lt $deadline) {
                $ready = Invoke-Command -Session $session -ScriptBlock {
                    param($folder, $expected)
                    $marker = Join-Path $folder 'ready-for-virtual-power-off.json'
                    if (-not (Test-Path -LiteralPath $marker)) { return $false }
                    $json = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
                    return ($json.phase -ceq $expected -and
                            $json.type -ceq 'virtual_power_off_required')
                } -ArgumentList $guestWorkspace,$phase
                if ($ready -eq $true) { break }
                Start-Sleep -Seconds 2
            }
            if (-not $ready) { throw "No durable guest cut barrier observed; refused to turn off VM" }
        } finally {
            if ($session) { Remove-PSSession -Session $session -ErrorAction SilentlyContinue }
            $session = $null
        }

        # This is the critical distinction: no guest graceful-shutdown instruction
        # is sent. The host removes power from the *virtual* machine instantly.
        Stop-VM -Name $VMName -TurnOff -Force -Confirm:$false -ErrorAction Stop
        $stopped = Get-VM -Name $VMName
        if ($stopped.Id.ToString() -ne $vmId -or $stopped.State.ToString() -ne 'Off') {
            throw "Hyper-V did not prove the expected disposable VM is Off"
        }
        Start-VM -Name $VMName -ErrorAction Stop

        $after = $null
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                $after = New-PSSession -VMName $VMName -Credential $Credential -ErrorAction Stop
                break
            } catch {
                Start-Sleep -Seconds 5
            }
        }
        if (-not $after) { throw "VM was not reachable by PowerShell Direct after power restoration" }
        try {
            $guest = Invoke-Command -Session $after -ScriptBlock {
                param($tools, $folder)
                $output = & python (Join-Path $tools 'powerloss-guest-fixture.py') recover --workspace $folder
                if ($LASTEXITCODE -ne 0) { throw 'Guest Git restoration could not be proven' }
                return ($output | Select-Object -Last 1)
            } -ArgumentList $guestTools,$guestWorkspace
            $proof = $guest | ConvertFrom-Json
            if ($proof.status -cne 'virtual_powercut_guest_recovered' -or
                $proof.phase -cne $phase -or
                $proof.exact_original_git_snapshot_restored -ne $true) {
                throw "Guest recovery certificate failed strict verification"
            }
            $results += @{
                phase = $phase
                virtual_power_cut = 'HyperV.Stop-VM -TurnOff'
                booted_again = $true
                exact_restoration = $true
                original_head = $proof.original_head
                baseline_sha256 = $proof.baseline_sha256
            }
        } finally {
            Remove-PSSession -Session $after -ErrorAction SilentlyContinue
        }
    }
    $allPass = ($results.Count -eq $Phases.Count)
} finally {
    # Never include VM credentials or secret values in the receipt.
    $report = [ordered]@{
        schema = 'jarvis-hyperv-virtual-powercut-v1'
        vm_id = $vmId
        guest_type = 'Windows'
        hypervisor = 'Hyper-V'
        mechanism = 'Stop-VM -TurnOff (virtual power removed)'
        phase_count = $Phases.Count
        results = $results
        virtual_powercut_test_passed = [bool]$allPass
        real_physical_electricity_cut_tested = $false
        physical_power_loss_certified = $false
        installer_tested_in_this_lab = $false
    }
    $report | ConvertTo-Json -Depth 7 |
        Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
}
if (-not $allPass) { throw "Virtual power-cut recovery NOT VERIFIED" }
Write-Host "PASS: disposable Windows Hyper-V guest virtual power-off and exact Git recovery. Receipt: $ReceiptPath"
