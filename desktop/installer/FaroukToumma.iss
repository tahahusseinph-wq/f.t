; مثبّت ويندوز لتطبيق الأدمن — يُبنى تلقائياً في GitHub Actions بعد PyInstaller
#define AppName "مجموعة فاروق الطعمة التجارية"
#define AppNameEn "Farouk Toumma Trading Group"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A41-6B7D-4E2A-9C51-3F7A1D2E0B11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppNameEn}
DefaultDirName={autopf}\FaroukToumma
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\FaroukToumma.exe
SetupIconFile=..\..\assets\icon.ico
OutputDir=Output
OutputBaseFilename=FaroukToumma-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes

[Languages]
#if FileExists(CompilerPath + "Languages\Arabic.isl")
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\FaroukToumma\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\FaroukToumma.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\FaroukToumma.exe"; Tasks: desktopicon

[Run]
; السماح لسيرفر الموبايل في جدار حماية ويندوز (الشبكات الخاصة فقط)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""FaroukToumma"" dir=in action=allow program=""{app}\FaroukToumma.exe"" profile=private enable=yes"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\FaroukToumma.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""FaroukToumma"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: "fw"
