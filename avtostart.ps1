# Kompyuter yoqilganda start_bot.cmd o'zi ishga tushishi uchun "Автозагрузка" papkasiga yorliq qo'yadi.
# O'chirish:  powershell -ExecutionPolicy Bypass -File avtostart.ps1 -Remove
param([switch]$Remove)

$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'Elegant Media zakaz boti.lnk'

if ($Remove) {
    Remove-Item $link -ErrorAction SilentlyContinue
    Write-Host "Avtostart o'chirildi."
    return
}

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = Join-Path $PSScriptRoot 'start_bot.cmd'
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle = 7  # kichraytirilgan oynada
$s.Description = 'Elegant Media zakaz boti'
$s.Save()
Write-Host "Tayyor: $link"
