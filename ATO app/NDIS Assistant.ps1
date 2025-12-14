Add-Type -AssemblyName System.Windows.Forms

$PYTHON_EXE = "C:\Users\alles\AppData\Local\Programs\Python\Python314\python.exe"
$APP_SCRIPT = "C:\Users\alles\My Drive\ATO app\app.py"
$ROOT_DIR = "C:\Users\alles\My Drive\ATO app"

# Read Google Drive path from config.ini
$CONFIG_PATH = "$ROOT_DIR\config.ini"
$GOOGLE_DRIVE = "C:\Program Files\Google\Drive File Stream\118.0.1.0\GoogleDriveFS.exe"
if (Test-Path $CONFIG_PATH) {
    $config = Get-Content $CONFIG_PATH | Select-String "google_drive_path"
    if ($config) {
        $GOOGLE_DRIVE = ($config -split '=')[1].Trim()
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "NDIS Assistant Ready?"
$form.Size = "500,180"
$form.StartPosition = "CenterScreen"
$form.TopMost = $true

$label = New-Object System.Windows.Forms.Label
$label.Text = "Only press Continue once you have:`n1. Put new screenshots in Google Drive`n2. Confirmed sync is complete (green checkmark)"
$label.Location = "10,10"
$label.Size = "460,60"
$form.Controls.Add($label)

$btnDrive = New-Object System.Windows.Forms.Button
$btnDrive.Text = "OPEN GOOGLE DRIVE"
$btnDrive.Location = "50,80"
$btnDrive.Size = "150,30"
$btnDrive.Add_Click({
    if (Test-Path $GOOGLE_DRIVE) {
        Start-Process $GOOGLE_DRIVE
    } else {
        [System.Windows.Forms.MessageBox]::Show("Drive app not found. Please open manually.", "Error")
    }
})
$form.Controls.Add($btnDrive)

$btnContinue = New-Object System.Windows.Forms.Button
$btnContinue.Text = "CONTINUE TO APP"
$btnContinue.Location = "250,80"
$btnContinue.Size = "150,30"
$btnContinue.Add_Click({ $form.DialogResult = [System.Windows.Forms.DialogResult]::OK; $form.Close() })
$form.Controls.Add($btnContinue)

$form.AcceptButton = $btnContinue

if ($form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    Set-Location $ROOT_DIR
    & $PYTHON_EXE $APP_SCRIPT
}