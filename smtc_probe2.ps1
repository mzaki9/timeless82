$ErrorActionPreference = "Stop"
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
$mgr = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync().GetResults()
$s = $mgr.GetCurrentSession()
if ($null -eq $s) { Write-Host "NO-SESSION"; exit 0 }
Write-Host ("source: " + $s.SourceAppUserModelId)
Write-Host ("status: " + $s.GetPlaybackInfo().PlaybackStatus)
$p = $s.TryGetMediaPropertiesAsync().GetResults()
Write-Host ("TITLE: " + $p.Title)
Write-Host ("ARTIST: " + $p.Artist)
Write-Host ("ALBUM: " + $p.AlbumTitle)
