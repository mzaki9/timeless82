# tray.ps1 — tray menu + autostart for nowlive.py (zero deps, WinForms only).
#   powershell -File tray.ps1                       # tray icon (default)
#   powershell -File tray.ps1 -Action start|stop|enable|disable|status|install|uninstall|icon
# Menu: Enabled (start/stop nowlive), Start with Windows (add/remove the
# Startup shortcut), Open log, Exit.
# Enabled is persisted in tray.state, so unchecking it survives a reboot:
# the tray still starts at login but leaves nowlive off until you re-check it.
# Icon: drawn in-process (accent keycap + keyboard glyph) in six sizes, and it
# swaps to a grey keycap while nowlive is off. -IconPath overrides it with a
# user .ico/.png. -Action icon dumps the generated pair for eyeballing.
param(
    [ValidateSet('tray', 'start', 'stop', 'enable', 'disable', 'status', 'install', 'uninstall', 'icon')]
    [string]$Action = 'tray',
    [string]$NowLiveArgs = '--direct',
    [string]$IconPath = '',
    [switch]$NoAutoStart
)

$ErrorActionPreference = 'Stop'
$HERE = $PSScriptRoot
$LOG = Join-Path $HERE 'nowlive.log'
$ERRLOG = Join-Path $HERE 'nowlive.err.log'
$LNK = Join-Path ([Environment]::GetFolderPath('Startup')) 'timeless82-tray.lnk'
$PIDFILE = Join-Path $HERE 'nowlive.pid'
$STATE = Join-Path $HERE 'tray.state'
$PS = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Install-Autostart {
    $sh = New-Object -ComObject WScript.Shell
    $l = $sh.CreateShortcut($LNK)
    $l.TargetPath = $PS
    $l.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$HERE\tray.ps1`""
    $l.WorkingDirectory = $HERE
    $l.WindowStyle = 7
    $l.Description = 'Timeless82 now-playing OLED tray'
    $l.Save()
}
function Uninstall-Autostart { if (Test-Path $LNK) { Remove-Item $LNK -Force } }
function Test-Autostart { Test-Path $LNK }

# Persisted "Enabled" preference: 1/0 in tray.state, default on. The tray
# window itself is not the source of truth, so a crash cannot silently
# disable the loop and an outside `-Action disable` reaches a running tray.
function Get-Desired {
    if (-not (Test-Path $STATE)) { return $true }
    return (Get-Content $STATE -ErrorAction SilentlyContinue) -notmatch '^\s*0\s*$'
}
function Set-Desired([bool]$v) {
    Set-Content -Path $STATE -Value $(if ($v) { '1' } else { '0' })
}

function Live-Pid {
    if ($script:proc -and -not $script:proc.HasExited) { return $script:proc.Id }
    if (Test-Path $PIDFILE) {
        $p = Get-Process -Id ([int](Get-Content $PIDFILE)) -ErrorAction SilentlyContinue
        # pid reuse guard: only trust it if it is still the interpreter.
        if ($p -and $p.ProcessName -match '^(py|python|pythonw)$') { return $p.Id }
    }
    return 0
}
function Start-Live {
    if (Live-Pid) { return }
    $script:proc = Start-Process -FilePath 'py' `
        -ArgumentList (@('-3', (Join-Path $HERE 'nowlive.py')) + ($NowLiveArgs -split '\s+' | Where-Object { $_ })) `
        -WorkingDirectory $HERE -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $LOG -RedirectStandardError $ERRLOG
    Set-Content -Path $PIDFILE -Value $script:proc.Id
    Write-Host "nowlive started pid=$($script:proc.Id) args=$NowLiveArgs"
}
function Stop-Live {
    $id = Live-Pid
    if ($id) {
        & taskkill.exe /PID $id /T /F 2>&1 | Out-Null
        Write-Host "nowlive stopped pid=$id"
    }
    $script:proc = $null
    if (Test-Path $PIDFILE) { Remove-Item $PIDFILE -Force }
}
function Test-Live { [bool](Live-Pid) }

# --- icon: drawn in-process, no image files needed -------------------------
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ICON_SIZES = 16, 20, 24, 32, 48, 64
$GLYPH_KEYBOARD = [char]0xE765  # KeyboardClassic
$GLYPH_NOTE = [char]0xE8D6      # MusicInfo

# Segoe Fluent Icons on Win11, MDL2 on older builds; null = draw a fallback shape.
function Get-IconFont([single]$px) {
    if ($null -eq $script:iconFontName) {
        $have = (New-Object System.Drawing.Text.InstalledFontCollection).Families |
                ForEach-Object { $_.Name }
        $script:iconFontName = @('Segoe Fluent Icons', 'Segoe MDL2 Assets') |
            Where-Object { $have -contains $_ } | Select-Object -First 1
    }
    if (-not $script:iconFontName) { return $null }
    return New-Object System.Drawing.Font($script:iconFontName, $px, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
}

# One keycap: rounded square (accent when on, grey when off) + centered glyph.
function New-KeycapBitmap([int]$s, [bool]$on) {
    $bmp = New-Object System.Drawing.Bitmap($s, $s, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $g.Clear([System.Drawing.Color]::Transparent)

    $fill = if ($on) { [System.Drawing.Color]::FromArgb(255, 37, 99, 235) }   # blue-600
            else { [System.Drawing.Color]::FromArgb(255, 82, 88, 99) }        # grey
    $ink = if ($on) { [System.Drawing.Color]::White } else { [System.Drawing.Color]::FromArgb(255, 205, 210, 218) }

    $r = [single]($s * 0.22)
    $d = [single]($r * 2)
    $e = [single]($s - 1)
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $p.AddArc([single]0, [single]0, $d, $d, 180, 90)
    $p.AddArc([single]($e - $d), [single]0, $d, $d, 270, 90)
    $p.AddArc([single]($e - $d), [single]($e - $d), $d, $d, 0, 90)
    $p.AddArc([single]0, [single]($e - $d), $d, $d, 90, 90)
    $p.CloseFigure()
    $b = New-Object System.Drawing.SolidBrush($fill)
    $g.FillPath($b, $p)
    $b.Dispose(); $p.Dispose()

    $font = Get-IconFont ([single]($s * 0.84))
    $ib = New-Object System.Drawing.SolidBrush($ink)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = [System.Drawing.StringAlignment]::Center
    $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
    # The glyph's line box sits high relative to its ink, so nudge down; and
    # below 24px the outline collapses to hairline, so stamp it 4x sub-pixel
    # offset to hold a ~1px stroke.
    $dy = [single]($s * 0.06)
    $offs = if ($s -lt 24) { @(@(0, 0), @(0.35, 0.35)) } else { @(@(0, 0)) }
    if ($font) {
        foreach ($o in $offs) {
            $rect = New-Object System.Drawing.RectangleF(
                [single]$o[0], [single]($o[1] + $dy), [single]$s, [single]$s)
            $g.DrawString($GLYPH_KEYBOARD, $font, $ib, $rect, $fmt)
        }
        $font.Dispose()
    } else {
        # No icon font: three key rows, still reads as a keyboard.
        for ($i = 0; $i -lt 3; $i++) {
            $y = [single]($s * (0.34 + 0.17 * $i))
            $g.FillRectangle($ib, [single]($s * 0.24), $y, [single]($s * 0.52), [single]($s * 0.10))
        }
    }
    $ib.Dispose(); $fmt.Dispose(); $g.Dispose()
    return $bmp
}

# Multi-size .ico (DIB/32bpp entries, the universally supported flavour).
function Get-IcoBytes([System.Drawing.Bitmap[]]$bmps) {
    $blobs = New-Object System.Collections.ArrayList
    foreach ($b in $bmps) {
        $rect = New-Object System.Drawing.Rectangle(0, 0, $b.Width, $b.Height)
        $ld = $b.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $stride = $ld.Stride
        $raw = New-Object byte[] ($stride * $b.Height)
        [System.Runtime.InteropServices.Marshal]::Copy($ld.Scan0, $raw, 0, $raw.Length)
        $b.UnlockBits($ld)
        $xor = New-Object byte[] ($b.Width * $b.Height * 4)
        for ($y = 0; $y -lt $b.Height; $y++) {   # DIB rows are bottom-up
            [Array]::Copy($raw, ($b.Height - 1 - $y) * $stride, $xor, $y * $b.Width * 4, $b.Width * 4)
        }
        $maskRow = [int][Math]::Ceiling($b.Width / 32.0) * 4
        $and = New-Object byte[] ($maskRow * $b.Height)   # 32bpp: alpha in XOR, mask empty
        $im = New-Object System.IO.MemoryStream
        $iw = New-Object System.IO.BinaryWriter($im)
        $iw.Write([uint32]40)
        $iw.Write([int32]$b.Width); $iw.Write([int32]($b.Height * 2))
        $iw.Write([uint16]1); $iw.Write([uint16]32); $iw.Write([uint32]0)
        $iw.Write([uint32]($xor.Length + $and.Length))
        $iw.Write([int32]0); $iw.Write([int32]0); $iw.Write([uint32]0); $iw.Write([uint32]0)
        $iw.Write($xor); $iw.Write($and); $iw.Flush()
        [void]$blobs.Add($im.ToArray())
    }
    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter($ms)
    $bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$bmps.Count)
    $off = 6 + 16 * $bmps.Count
    for ($i = 0; $i -lt $bmps.Count; $i++) {
        $bw.Write([byte]$(if ($bmps[$i].Width -ge 256) { 0 } else { $bmps[$i].Width }))
        $bw.Write([byte]$(if ($bmps[$i].Height -ge 256) { 0 } else { $bmps[$i].Height }))
        $bw.Write([byte]0); $bw.Write([byte]0)
        $bw.Write([uint16]1); $bw.Write([uint16]32)
        $bw.Write([uint32]$blobs[$i].Length); $bw.Write([uint32]$off)
        $off += $blobs[$i].Length
    }
    foreach ($blob in $blobs) { $bw.Write([byte[]]$blob) }
    $bw.Flush()
    return $ms.ToArray()
}

function New-KeycapIcon([bool]$on) {
    if ($IconPath) {
        if (-not (Test-Path $IconPath)) { throw "icon not found: $IconPath" }
        if ([System.IO.Path]::GetExtension($IconPath) -ieq '.ico') {
            return New-Object System.Drawing.Icon((Resolve-Path $IconPath).Path)
        }
        $bmp = New-Object System.Drawing.Bitmap((Resolve-Path $IconPath).Path)  # png/jpg
        $h = $bmp.GetHicon()
        return [System.Drawing.Icon]::FromHandle($h)
    }
    $bmps = @()
    foreach ($s in $ICON_SIZES) { $bmps += New-KeycapBitmap $s $on }
    $bytes = Get-IcoBytes $bmps
    # Icon(Stream) keeps the stream alive, so hold every one for the process life.
    $ms = New-Object System.IO.MemoryStream($bytes, $false)
    $ms.Position = 0
    [void]$script:iconStreams.Add($ms)
    foreach ($b in $bmps) { $b.Dispose() }
    return New-Object System.Drawing.Icon -ArgumentList $ms
}
$script:iconStreams = New-Object System.Collections.ArrayList

switch ($Action) {
    'install' { Install-Autostart; Write-Host "autostart -> $LNK"; exit 0 }
    'uninstall' { Uninstall-Autostart; Write-Host 'autostart removed'; exit 0 }
    'status' {
        Write-Host ("enabled={0} live={1} autostart={2}" -f
            (Get-Desired), (Test-Live), (Test-Autostart))
        exit 0
    }
    'start' { Stop-Live; Start-Live; Set-Desired $true; exit 0 }
    'enable' { Set-Desired $true; Start-Live; exit 0 }
    'disable' { Set-Desired $false; Stop-Live; exit 0 }
    'stop' { Stop-Live; Set-Desired $false; exit 0 }
    'icon' {
        # Dump the generated pair + a pixel census, so the art is checkable
        # without a running tray (and openable in Explorer).
        foreach ($on in @($true, $false)) {
            $bmps = @(); foreach ($s in $ICON_SIZES) { $bmps += New-KeycapBitmap $s $on }
            $name = if ($on) { 'tray-icon-on.ico' } else { 'tray-icon-off.ico' }
            $path = Join-Path $HERE $name
            [System.IO.File]::WriteAllBytes($path, (Get-IcoBytes $bmps))
            $b = New-KeycapBitmap 32 $on
            $opaque = 0; $ink = 0
            for ($y = 0; $y -lt 32; $y++) {
                for ($x = 0; $x -lt 32; $x++) {
                    $c = $b.GetPixel($x, $y)
                    if ($c.A -gt 200) { $opaque++ }
                    if ($c.A -gt 200 -and $c.R -gt 200 -and $c.G -gt 200) { $ink++ }
                }
            }
            $b.Dispose()
            Write-Host ("{0}  {1} bytes  font={2}  32px opaque={3} ink={4}" -f
                $path, (Get-Item $path).Length, $(if ($script:iconFontName) { $script:iconFontName } else { 'none' }), $opaque, $ink)
            foreach ($x in $bmps) { $x.Dispose() }
        }
        exit 0
    }
}

# --- tray mode: one instance per session, else two nowlive loops fight ---
$mutex = New-Object System.Threading.Mutex($false, 'Local\timeless82-tray')
if (-not $mutex.WaitOne(0)) { Write-Host 'tray already running'; exit 1 }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

if (-not (Test-Autostart) -and -not $NoAutoStart) { Install-Autostart }

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miEnabled = New-Object System.Windows.Forms.ToolStripMenuItem 'Enabled'
$miEnabled.CheckOnClick = $true
$miAuto = New-Object System.Windows.Forms.ToolStripMenuItem 'Start with Windows'
$miAuto.CheckOnClick = $true
$miAuto.Checked = Test-Autostart
$miLog = New-Object System.Windows.Forms.ToolStripMenuItem 'Open log'
$miExit = New-Object System.Windows.Forms.ToolStripMenuItem 'Exit'
$menu.Items.AddRange(@($miEnabled, $miAuto,
    (New-Object System.Windows.Forms.ToolStripSeparator), $miLog, $miExit))

$script:iconOn = New-KeycapIcon $true
$script:iconOff = New-KeycapIcon $false

$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = $script:iconOff
$icon.Text = 'Timeless82 now-playing'
$icon.ContextMenuStrip = $menu
$icon.Visible = $true

# The persisted preference is the truth, so an outside `-Action disable`
# flips the menu and a crash restarts nowlive (with a retry gap so a broken
# interpreter cannot spin).
$script:lastTry = [datetime]::MinValue
function Sync-Tray {
    $want = Get-Desired
    $live = Test-Live
    if ($miEnabled.Checked -ne $want) { $miEnabled.Checked = $want }
    if ($miAuto.Checked -ne (Test-Autostart)) { $miAuto.Checked = Test-Autostart }
    $icon.Icon = $(if ($live) { $script:iconOn } else { $script:iconOff })
    $icon.Text = 'Timeless82 now-playing: ' + $(if ($live) { 'on' } else { 'off' })
}
function Reconcile {
    $want = Get-Desired
    if ($want -eq (Test-Live)) { return }
    if (-not $want) { Stop-Live; return }
    if (([datetime]::Now - $script:lastTry).TotalSeconds -lt 15) { return }
    $script:lastTry = [datetime]::Now
    Start-Live
}

$miEnabled.Add_Click({
    Set-Desired $miEnabled.Checked
    $script:lastTry = [datetime]::MinValue
    Reconcile
    Sync-Tray
})
$miAuto.Add_Click({
    if ($miAuto.Checked) { Install-Autostart } else { Uninstall-Autostart }
    Sync-Tray
})
$miLog.Add_Click({
    if (-not (Test-Path $LOG)) { New-Item -ItemType File -Path $LOG | Out-Null }
    Start-Process notepad.exe $LOG
})
$miExit.Add_Click({
    Stop-Live
    $icon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 2000
$timer.Add_Tick({ Reconcile; Sync-Tray })
$timer.Start()

Reconcile
Sync-Tray
[System.Windows.Forms.Application]::Run()
$timer.Stop()
$icon.Dispose()
