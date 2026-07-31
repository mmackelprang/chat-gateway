#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotent Google Cloud setup for chat-gateway tier 2 (two-way Chat app).
  PowerShell sibling of gcloud-setup.sh — same steps, same order, same output.

.DESCRIPTION
  Why a .ps1 exists alongside the .sh (this project is developed on Windows 11):

  1. MSYS / Git-Bash argument path-mangling — the headline reason. Under Git
     Bash on Windows, an argument containing forward slashes such as
     --role="roles/pubsub.publisher" is rewritten into a Windows path (e.g.
     C:/msys64/roles/pubsub.publisher) before gcloud ever sees it, silently
     breaking the IAM binding calls. PowerShell does no such rewriting.
  2. `chmod 600` is a no-op on NTFS — the bash script cannot actually restrict
     the minted SA key on Windows. This script uses icacls instead.
  3. gcloud is usually not on PATH in non-interactive Windows shells; this
     script locates the SDK itself (see Resolve-Gcloud).

  The .sh remains the POSIX path and is unchanged — this is an addition, not a
  replacement. Both are idempotent: re-running against an already-provisioned
  project is a no-op.

.EXAMPLE
  .\gcloud-setup.ps1 -ProjectId your-project-id

.NOTES
  Prereq: gcloud auth login; the project already exists (or uncomment the
  create line in step 1). Never prints key material or webhook URLs — error
  and progress paths name identities and paths only.

  This script is project-agnostic and names no project on purpose — the id of
  the project this repo actually runs on is deliberately not repeated here; see
  docs/google-cloud-setup.md. The example above used to read
  `chat-gateway-prod`, which was DELETED on 2026-07-30, so copy-pasting it
  aimed every gcloud call below at a project that no longer exists.

  ENCODING: keep this file UTF-8 **with BOM**. Windows PowerShell 5.1 reads a
  BOM-less file as ANSI/cp1252, which turns the non-ASCII characters below
  (⚠, em dashes, §) into curly quotes — and PowerShell treats curly quotes as
  string delimiters, so the script fails to parse. Verified: BOM-less, 5.1
  reports ~10 bogus syntax errors; with BOM, 5.1 and 7.x both parse clean.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectId,

    [string] $Topic = 'chat-gateway-events',
    [string] $Subscription = 'chat-gateway-sub',
    [string] $SaName = 'chat-gateway',

    # Relative values resolve against this script's directory (iac/), so the
    # key lands in the same place regardless of the caller's working dir.
    #
    # DEFAULT: derived from -ProjectId, just below the param block (CG-51) —
    # the reasoning lives there so it sits beside the guard it depends on.
    [string] $KeyFile = '',

    # Deliberate escape hatch for that guard — pass it only when you really do
    # want a second key beside an existing one (several projects on one host).
    [switch] $AllowSecondKey
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# PS 7.3+ turns native non-zero exits into terminating errors when EAP is
# Stop. That would abort the script on the `describe` probes below, which are
# *expected* to fail when a resource does not exist yet. Opt out and check
# $LASTEXITCODE explicitly instead (see Invoke-Gcloud / Test-GcloudResource).
if (Test-Path 'Variable:PSNativeCommandUseErrorActionPreference') {
    $PSNativeCommandUseErrorActionPreference = $false
}

$SaEmail = "$SaName@$ProjectId.iam.gserviceaccount.com"

# The key filename is DERIVED FROM $ProjectId (CG-51, user decision 2026-07-30)
# so it can never name a project that does not exist.
#
# It used to default to a flat 'chat-gateway-sa.json', and the "already exists —
# not minting another" branch near the bottom matches on FILENAME ONLY: it
# cannot tell which project a key belongs to, so a key left over from a
# DIFFERENT project satisfied it. That was not hypothetical — the deleted
# `chat-gateway-prod` minted its key under that exact default, so a working tree
# which provisioned it still holds an iac\chat-gateway-sa.json that
# authenticates to nothing, and re-running here for a fresh project printed "not
# minting another" and then emitted a .env block pointing
# GOOGLE_APPLICATION_CREDENTIALS at that dead credential.
#
# CG-19 declined to rename the default, with evidence: ANY fixed new name stops
# matching on a host that holds the old key and mints a SECOND service-account
# key, and key sprawl is worse than a documented trap. That objection is
# answered by the GUARD below, not by the derivation — when the derived name is
# absent but a sibling `<SaName>-sa*.json` is present, this script refuses to
# mint, says exactly what it found, and exits non-zero. An unresolved key is
# loud; a second credential nobody knows about is not.
if (-not $KeyFile) { $KeyFile = "$SaName-sa-$ProjectId.json" }

# The principal Google Chat publishes events AS. Per Google's docs it is:
$ChatEventsPublisher = 'serviceAccount:chat-api-push@system.gserviceaccount.com'
#
# WHICH principal actually published this project's first events is CLOSED BY
# CIRCUMSTANCE, not answered — it is not a gap to close and not a task, and this
# script no longer asks you to settle it (CG-35). Both this principal and the
# Workspace Add-ons service agent (bound further down) were bound on
# `chat-gateway-prod`; that project was DELETED on 2026-07-30, so the question
# can never be settled. See CLAUDE.md, "Verification ledger".
#
# Two reasons it was never answerable from inside this script anyway, and both
# still apply to YOUR project: GCP accepts an IAM binding to a
# *@system.gserviceaccount.com principal WITHOUT validating that it exists, so a
# clean `add-iam-policy-binding` proves nothing; and "a real event landed in the
# subscription" does not attribute itself, because both principals are
# publishers.
#
# THE BINDING BELOW STAYS, and so does the add-ons one further down — a classic
# Chat app (what this script provisions, and what we run) needs the Chat-API
# publisher, and a project that does deploy an add-on needs the other.
#
# On the wording: this comment used to end by declaring the question a pending
# hard-rule-#3 flag. That flag was MISAPPLIED — rule #3's flag marks CODE not yet
# exercised against real Google endpoints, and an unanswerable question about
# which principal published is not that. Dropping it (CG-35, user sign-off
# 2026-07-30) is removing a misapplied flag, NOT clearing a real one, and is no
# precedent for clearing one.

function Resolve-Gcloud {
    <#  Locate gcloud without assuming PATH or a hardcoded username.
        Prefer a .cmd/.exe shim — the extension-less `gcloud` that ships in the
        SDK bin dir is a bash script and is not executable from PowerShell. #>
    foreach ($name in @('gcloud.cmd', 'gcloud.exe', 'gcloud')) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($cmd -and $cmd.Source -match '\.(cmd|exe|bat)$') { return $cmd.Source }
    }

    $roots = @(
        $env:LOCALAPPDATA,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ }

    foreach ($root in $roots) {
        $candidate = Join-Path $root 'Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    throw @'
gcloud not found. Install the Google Cloud SDK, or open a shell where it is on
PATH. Default Windows install location:
  %LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin
Then authenticate with:  gcloud auth login
'@
}

function Invoke-Gcloud {
    <#  Run gcloud, fail loudly on a non-zero exit. -Quiet discards stdout
        only — the .sh equivalent of `>/dev/null`. stderr still reaches the
        terminal, because gcloud reports status and warnings there
        ("Updated property [core/project].", deprecation and ADC notices) and
        a Windows user should see exactly what a POSIX user sees. #>
    param(
        [Parameter(Mandatory = $true)][string[]] $GcloudArgs,
        [switch] $Quiet
    )
    $code = 1   # pre-set: a launch failure must not leave this unassigned
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # gcloud chatters on stderr; not an error
    try {
        if ($Quiet) { & $script:Gcloud @GcloudArgs | Out-Null }
        else        { & $script:Gcloud @GcloudArgs }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }

    if ($code -ne 0) { throw "gcloud $($GcloudArgs -join ' ') failed (exit $code)" }
}

function Test-GcloudResource {
    <#  Existence probe. A non-zero exit means "not there", NOT "abort" —
        this is the idempotency hinge, so it must never throw. Discards stdout
        AND stderr (matching the .sh probes' `>/dev/null 2>&1`): a missing
        resource legitimately prints a NOT_FOUND on stderr, and that is an
        expected outcome here, not something to show the user. #>
    param([Parameter(Mandatory = $true)][string[]] $GcloudArgs)
    $code = 1
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $script:Gcloud @GcloudArgs 2>&1 | Out-Null
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
        $global:LASTEXITCODE = 0
    }
    return ($code -eq 0)
}

$script:Gcloud = Resolve-Gcloud
Write-Host "== gcloud: $script:Gcloud"

if ([System.IO.Path]::IsPathRooted($KeyFile)) {
    $KeyPath = $KeyFile
}
else {
    $KeyPath = Join-Path $PSScriptRoot $KeyFile
}
# $KeyName is what the .env block below emits: it is a HOST path
# (/srv/chat-gateway/...), so it takes the leaf, never the caller's local path.
# The .sh sibling concatenated its raw ${KEY_FILE} there and emitted
# `/srv/chat-gateway/C:/…/key.json` for an absolute input (CG-35b, measured);
# it does the same basename now, so the pair is at parity on this input.
$KeyName = Split-Path -Leaf $KeyPath
$KeyDir = Split-Path -Parent $KeyPath
$KeyUnresolved = $false

Write-Host "== project: $ProjectId"
# Invoke-Gcloud @('projects','create',$ProjectId,'--name=chat-gateway')   # if not created yet
Invoke-Gcloud @('config', 'set', 'project', $ProjectId) -Quiet

# appsmarket-component = the Google Workspace Marketplace SDK.
#
# ⚠ CORRECTED 2026-07-30 (CG-19) — DO NOT REINSTATE THE OLD CLAIM. This comment
# used to read "Without it the app never appears under Apps & integrations ->
# Add apps". That is FALSE, and it is the exact sentence that put this project
# on the Workspace Add-ons runtime — which is why the correction is left here as
# a warning rather than quietly deleted. If you are choosing a runtime for a NEW
# project, read the ADR cited below BEFORE you run this script.
#
# Installability comes from Chat API -> Configuration -> Visibility: list your
# own address (or a Google Group) there and you can add the app to a space
# immediately, before any Marketplace publish. Two sources say so and their
# SCOPES DIFFER — do not merge them into one universal sentence, which is the
# exact mistake this comment exists to undo:
#   * classic, which is what this script provisions — "the Chat API lets you
#     share your Chat app with specific people in your Google Workspace
#     organization. The people that you specify can add the Chat app to a space
#     and test its features before you publish it to the Marketplace"
#     https://developers.google.com/workspace/chat/test-interactive-features
#   * add-ons specifically — "To deploy and test an add-on in Chat, you must use
#     the Chat API's Visibility setting. Any visibility or testing settings that
#     you've configured in the Google Workspace Marketplace SDK are ignored"
#     https://developers.google.com/workspace/add-ons/chat
# Marketplace publishing is needed only to reach people BEYOND that Visibility
# list, and it is console-only either way.
#
# The API stays enabled: it is harmless, it costs nothing, and it shortens a
# later publish. It is simply not a prerequisite for anything provisioned here.
# Full account: CG-6, which corrected the same claim in
# docs/google-cloud-setup.md, and ADR-0001 §5 option D / §14 —
# docs/architecture/decisions/2026-07-29-tier2-interaction-model.md.
Write-Host '== enabling APIs (chat, pubsub, workspace add-ons, marketplace SDK)'
Invoke-Gcloud @('services', 'enable', 'chat.googleapis.com', 'pubsub.googleapis.com',
    'gsuiteaddons.googleapis.com', 'appsmarket-component.googleapis.com')

Write-Host "== service account: $SaEmail"
if (-not (Test-GcloudResource @('iam', 'service-accounts', 'describe', $SaEmail))) {
    Invoke-Gcloud @('iam', 'service-accounts', 'create', $SaName, '--display-name=chat-gateway')
}

Write-Host "== topic: $Topic"
if (-not (Test-GcloudResource @('pubsub', 'topics', 'describe', $Topic))) {
    Invoke-Gcloud @('pubsub', 'topics', 'create', $Topic)
}

Write-Host '== grant Chat''s event publisher on the topic'
Invoke-Gcloud @(
    'pubsub', 'topics', 'add-iam-policy-binding', $Topic,
    "--member=$ChatEventsPublisher", '--role=roles/pubsub.publisher'
) -Quiet

# The Workspace Add-ons runtime publishes as a per-project service agent that
# does not exist until created — omitting it is the 2026-07-29 field failure
# ("<app> is not responding", nothing in the subscription). See the .sh sibling
# for the full note, including why the fix is circumstantial evidence only, and
# docs/google-cloud-setup.md for the failure signature.
# `gcloud beta` needs the beta component; gcloud offers to install it on first
# use. Re-running is a no-op — the command returns the existing identity.
Write-Host '== ensure the Workspace Add-ons service agent exists'
Invoke-Gcloud @('beta', 'services', 'identity', 'create',
    '--service=gsuiteaddons.googleapis.com', "--project=$ProjectId") -Quiet

# Captures a VALUE, so it cannot go through Invoke-Gcloud (which discards
# stdout). Mirrors that helper's stderr handling instead: gcloud chatters on
# stderr and this script runs with $ErrorActionPreference = 'Stop'.
$ProjectNumber = $null
$code = 1   # pre-set: a launch failure must not leave this unassigned
$prev = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    # Capture first, THEN read $LASTEXITCODE. Piping straight into
    # Select-Object would short-circuit the pipeline and leave $LASTEXITCODE
    # holding a stale value from the previous gcloud call.
    $out = & $script:Gcloud @(
        'projects', 'describe', $ProjectId, '--format=value(projectNumber)'
    )
    $code = $LASTEXITCODE
    $ProjectNumber = @($out)[0]
}
finally { $ErrorActionPreference = $prev }
if ($code -ne 0) { throw "gcloud projects describe $ProjectId failed (exit $code)" }

# A blank project number would bind `service-@gcp-sa-...`, which GCP may accept
# without validating — reproducing exactly the false confidence the
# $ChatEventsPublisher comment above already warns about. Fail instead.
$ProjectNumber = "$ProjectNumber".Trim()
if (-not $ProjectNumber) {
    throw "could not resolve the project number for $ProjectId — cannot bind the add-ons service agent"
}
$AddonsPublisher = "serviceAccount:service-$ProjectNumber@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"

Write-Host "== grant the add-ons service agent publisher on the topic ($AddonsPublisher)"
Invoke-Gcloud @(
    'pubsub', 'topics', 'add-iam-policy-binding', $Topic,
    "--member=$AddonsPublisher", '--role=roles/pubsub.publisher'
) -Quiet

Write-Host "== subscription: $Subscription (pull)"
if (-not (Test-GcloudResource @('pubsub', 'subscriptions', 'describe', $Subscription))) {
    Invoke-Gcloud @(
        'pubsub', 'subscriptions', 'create', $Subscription,
        "--topic=$Topic", '--ack-deadline=30', '--message-retention-duration=24h'
    )
}

Write-Host '== grant the gateway SA subscribe'
Invoke-Gcloud @(
    'pubsub', 'subscriptions', 'add-iam-policy-binding', $Subscription,
    "--member=serviceAccount:$SaEmail", '--role=roles/pubsub.subscriber'
) -Quiet

# Filename-only check — it does not know which project the existing key belongs
# to. That is why the name is derived from $ProjectId and why the else-branch
# looks for predecessors. Full note: the $KeyFile derivation block just above
# $ChatEventsPublisher.
if (Test-Path -LiteralPath $KeyPath) {
    Write-Host "== key file $KeyPath already exists — not minting another"
}
else {
    # Do not silently mint a SECOND credential (CG-51). A sibling key under the
    # same naming convention almost always means "the key you want is already
    # here under another name" — a rename this script must not guess at.
    $Predecessors = @()
    if (Test-Path -LiteralPath $KeyDir) {
        $Predecessors = @(
            Get-ChildItem -LiteralPath $KeyDir -File -Filter "$SaName-sa*.json" |
                Select-Object -ExpandProperty Name | Sort-Object
        )
    }

    if ($Predecessors.Count -gt 0 -and -not $AllowSecondKey) {
        Write-Host "!! NOT minting a key. $KeyName is absent, but $KeyDir already holds:"
        foreach ($existing in $Predecessors) { Write-Host "!!   $existing" }
        Write-Host '!! Minting now would leave two service-account keys on this host and no'
        Write-Host '!! record of which one is live. Resolve it yourself, then re-run:'
        Write-Host '!!   * reuse an existing key      -> -KeyFile <that filename>'
        Write-Host '!!   * it belongs to a dead/other project -> move or delete it'
        Write-Host '!!   * you really do want another -> -AllowSecondKey (deliberate)'
        $KeyUnresolved = $true
    }
    else {
        Write-Host "== minting SA key -> $KeyPath (keep off-repo; owner-only ACL; SECRETS.md pointer)"
        Invoke-Gcloud @('iam', 'service-accounts', 'keys', 'create', $KeyPath, "--iam-account=$SaEmail")

        # chmod 600 is a no-op on NTFS. Break inheritance, grant only this user.
        icacls $KeyPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw @"
icacls failed (exit $LASTEXITCODE) — the key at $KeyPath may still be readable
by other principals. Lock it down before using it:
  icacls "$KeyPath" /inheritance:r /grant:r "%USERNAME%:(R,W)"
"@
        }
        Write-Host "== key ACL: inheritance removed, $($env:USERNAME) only (contents never printed)"
    }
}

Write-Host @"

== done. Console-only steps remain (docs/google-cloud-setup.md §5–7):
   Chat API Configuration page (app name/avatar, Pub/Sub topic), spaces, webhooks.

== .env block for the gateway host:
GATEWAY_ENABLE_PUBSUB=1
GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/$KeyName
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION=projects/$ProjectId/subscriptions/$Subscription
"@

if ($KeyUnresolved) {
    Write-Host ''
    Write-Host '!! Everything above is provisioned, but NO KEY WAS CREATED: the'
    Write-Host "!! GOOGLE_APPLICATION_CREDENTIALS line names $KeyName, which does not"
    Write-Host '!! exist. Exiting non-zero so this cannot pass unnoticed — see the !!'
    Write-Host '!! block above. Re-running once you have resolved it is a no-op for'
    Write-Host '!! everything else.'
    exit 3
}
