; ProfMute installer (Inno Setup 6). Built by build_dist.py from the files in dist\ProfMute:
;   ISCC /DAppVersion=<version> installer\ProfMute.iss
;
; It installs for the current user only, without administrator rights, because ProfMute writes
; next to its own exe: the Python environment, the logs, the settings and the editable lists.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E1C0B7A-93D4-4F5E-8A27-51B9C2D7E4A3}
AppName=ProfMute
AppVersion={#AppVersion}
AppPublisher=SevynTech
AppPublisherURL=https://github.com/SevynTech/ProfMute
AppSupportURL=https://github.com/SevynTech/ProfMute/issues
DefaultDirName={autopf}\ProfMute
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Redirection Guard is inherited by the download step below, where uv makes a folder link for
; Python and would then be refused access to its own link (error 448). The guard protects
; installers that run as administrator; this one never does, so nothing is given up.
RedirectionGuard=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ProfMute-Setup-{#AppVersion}
SetupIconFile=..\profmute.ico
UninstallDisplayIcon={app}\ProfMute.exe
UninstallDisplayName=ProfMute
VersionInfoVersion={#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; the libraries downloaded at the end of the installation
ExtraDiskSpaceRequired=2500000000

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\ProfMute\*"; DestDir: "{app}"; Excludes: "words.txt,models.txt"; Flags: recursesubdirs ignoreversion
; the lists people edit: never overwrite their copy when a newer version is installed over an old one
Source: "..\dist\ProfMute\words.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\dist\ProfMute\models.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{autoprograms}\ProfMute"; Filename: "{app}\ProfMute.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ProfMute"; Filename: "{app}\ProfMute.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[InstallDelete]
; installing over an older version: make the step below check the libraries again
Type: files; Name: "{app}\.venv\profmute-ready"

[Run]
Filename: "{app}\ProfMute.exe"; Parameters: "--setup"; StatusMsg: "Downloading Python and the speech recognition libraries, about 2.2 GB..."; Flags: waituntilterminated; BeforeInstall: Downloading(True); AfterInstall: Downloading(False)
Filename: "{app}\ProfMute.exe"; Description: "Open ProfMute now"; Flags: nowait postinstall skipifsilent

[Code]
// The download can take minutes and reports no percentage: keep the bar moving so it does not look stuck.
procedure Downloading(Busy: Boolean);
begin
  if Busy then
    WizardForm.ProgressGauge.Style := npbstMarquee
  else
    WizardForm.ProgressGauge.Style := npbstNormal;
end;

[UninstallDelete]
; what ProfMute downloaded or wrote by itself. The log folder is left alone: those are the user's records.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\launcher\__pycache__"
Type: files; Name: "{app}\profmute_gui.json"
Type: files; Name: "{app}\setup-log.txt"
