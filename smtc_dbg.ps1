$ErrorActionPreference = "Stop"
try {
  $t = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
  Write-Host "type-ok"
  $op = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
  Write-Host ("op-isnull=" + ($null -eq $op))
  if ($null -ne $op) {
    Write-Host ("optype=" + $op.GetType().FullName)
    Write-Host ("status=" + $op.Status)
  }
} catch {
  Write-Host ("EX: " + $_.Exception.Message)
}
