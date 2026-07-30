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
  the project this repo actually runs on is recorded once, in
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
    # ⚠ Pass a per-project -KeyFile — e.g. chat-gateway-sa-<project>.json. The
    # "already exists — not minting another" branch near the bottom matches on
    # FILENAME ONLY; it cannot tell which project a key belongs to, so a key
    # left over from a different project satisfies it. That is not
    # hypothetical: the deleted `chat-gateway-prod` minted its key under this
    # exact default, so any working tree that provisioned it still holds an
    # iac\chat-gateway-sa.json that authenticates to nothing. Re-run here for a
    # fresh project and the script prints "not minting another", then emits a
    # .env block pointing GOOGLE_APPLICATION_CREDENTIALS at that dead
    # credential.
    #
    # The default is left unchanged ON PURPOSE (CG-19): renaming it would make
    # this script mint a SECOND service-account key on every host that already
    # has one, and a comment fix must not create credentials as a side effect.
    [string] $KeyFile = 'chat-gateway-sa.json'
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

# ⚠ VERIFY on the Chat API Configuration page when you wire the topic:
# the principal Google Chat publishes events AS. Per current docs it is:
$ChatEventsPublisher = 'serviceAccount:chat-api-push@system.gserviceaccount.com'
# NOTE: GCP accepts an IAM binding to a *@system.gserviceaccount.com principal
# WITHOUT validating that it exists — a clean `add-iam-policy-binding` here
# proves nothing. Nor is "a real event landed in the subscription" sufficient:
# the Workspace Add-ons service agent (bound further down) is also a publisher,
# so an arriving event does not attribute itself to either principal. This
# stays ⚠ LIVE-UNVERIFIED until the principal is confirmed on the Chat API
# "Connection settings" console page.

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
$KeyName = Split-Path -Leaf $KeyPath

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
# immediately. Google states its Marketplace settings are ignored for Chat
# outright — "Any visibility or testing settings that you've configured in the
# Google Workspace Marketplace SDK are ignored"
# (https://developers.google.com/workspace/add-ons/chat). Marketplace publishing
# is needed only to reach people BEYOND that Visibility list, and it is
# console-only either way.
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

Write-Host '== grant Chat''s event publisher on the topic (VERIFY principal — see comment)'
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

# ⚠ Filename-only check — it does not know which project the existing key
# belongs to. See the -KeyFile note in the param block at the top.
if (Test-Path -LiteralPath $KeyPath) {
    Write-Host "== key file $KeyPath already exists — not minting another"
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

Write-Host @"

== done. Console-only steps remain (docs/google-cloud-setup.md §5–7):
   Chat API Configuration page (app name/avatar, Pub/Sub topic), spaces, webhooks.

== .env block for the gateway host:
GATEWAY_ENABLE_PUBSUB=1
GOOGLE_APPLICATION_CREDENTIALS=/srv/chat-gateway/$KeyName
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION=projects/$ProjectId/subscriptions/$Subscription
"@
