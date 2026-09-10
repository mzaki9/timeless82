$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
$op = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
$task = [System.WindowsRuntimeSystemExtensions]::AsTask($op)
$mgr = $task.GetAwaiter().GetResult()
$s = $mgr.GetCurrentSession()
if ($null -eq $s) { Write-Host "NO-SESSION"; exit 0 }
Write-Host ("source: " + $s.SourceAppUserModelId)
Write-Host ("status: " + $s.GetPlaybackInfo().PlaybackStatus)
$ptask = [System.WindowsRuntimeSystemExtensions]::AsTask($s.TryGetMediaPropertiesAsync())
$p = $ptask.GetAwaiter().GetResult()
Write-Host ("TITLE: " + $p.Title)
Write-Host ("ARTIST: " + $p.Artist)
Write-Host ("ALBUM: " + $p.AlbumTitle)
