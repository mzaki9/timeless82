$ErrorActionPreference = "Stop"
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
function AwaitOp($op) {
  while ($op.Status -eq 0) { Start-Sleep -Milliseconds 100 }
  if ($op.Status -ne 1) { throw ("op status " + $op.Status) }
  return $op.GetResults()
}
$mgr = AwaitOp([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync())
$s = $mgr.GetCurrentSession()
if ($null -eq $s) { Write-Host "NO-SESSION"; exit 0 }
Write-Host ("source: " + $s.SourceAppUserModelId)
Write-Host ("status: " + $s.GetPlaybackInfo().PlaybackStatus)
$p = AwaitOp($s.TryGetMediaPropertiesAsync())
Write-Host ("TITLE: " + $p.Title)
Write-Host ("ARTIST: " + $p.Artist)
Write-Host ("ALBUM: " + $p.AlbumTitle)
