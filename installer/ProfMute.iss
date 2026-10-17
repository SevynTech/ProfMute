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
Source: "..\dist\ProfMute\*"; DestDir: "{app}"; Excludes: "words.txt,models.txt,voice-models.txt"; Flags: recursesubdirs ignoreversion
; the lists people edit: never overwritten when a newer version is installed over an old one, and kept when
; ProfMute is uninstalled (unless "Remove everything" is ticked then), so a reinstall finds them again
Source: "..\dist\ProfMute\words.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\dist\ProfMute\models.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\dist\ProfMute\voice-models.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\ProfMute"; Filename: "{app}\ProfMute.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ProfMute"; Filename: "{app}\ProfMute.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[InstallDelete]
; installing over an older version: make the step below check the libraries again
Type: files; Name: "{app}\.venv\profmute-ready"

[Run]
Filename: "{app}\ProfMute.exe"; Parameters: "--setup"; StatusMsg: "Downloading Python and the speech recognition and voice removal libraries, about 4.7 GB..."; Flags: waituntilterminated; BeforeInstall: Downloading(True); AfterInstall: Downloading(False)
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

// Uninstalling: by default the word list, model lists, settings and logs stay, for a later install.
// "Remove everything" (unticked unless chosen) takes those too, and the Whisper models ProfMute downloaded into
// the user's Hugging Face folder (%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-*).
// Asked right after Windows' own "Are you sure you want to remove ProfMute?", before anything is removed.
function AskRemoveEverything(): Boolean;
var
  Form: TSetupForm;
  Intro, Note: TNewStaticText;
  Box: TNewCheckBox;
  OkButton: TNewButton;
begin
  Form := CreateCustomForm(ScaleX(460), ScaleY(190), False, True);
  try
    Form.Caption := 'Uninstall ProfMute';
    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.AutoSize := False;
    Intro.WordWrap := True;
    Intro.SetBounds(ScaleX(16), ScaleY(14), Form.ClientWidth - ScaleX(32), ScaleY(44));
    Intro.Caption := 'ProfMute and everything it downloaded into its folder will be removed. Your word list, '
      + 'settings and logs are kept, so installing ProfMute again picks them up.';
    Box := TNewCheckBox.Create(Form);
    Box.Parent := Form;
    Box.SetBounds(ScaleX(16), ScaleY(66), Form.ClientWidth - ScaleX(32), ScaleY(20));
    Box.Caption := 'Remove everything';
    Box.Checked := False;
    Note := TNewStaticText.Create(Form);
    Note.Parent := Form;
    Note.AutoSize := False;
    Note.WordWrap := True;
    Note.SetBounds(ScaleX(34), ScaleY(88), Form.ClientWidth - ScaleX(50), ScaleY(58));
    Note.Caption := 'Also your word list, settings and the logs in ProfMute''s folder, and the Whisper speech '
      + 'models it downloaded (about 3 GB, in your user folder). Your clean copies and clean subtitles are never '
      + 'removed.';
    OkButton := TNewButton.Create(Form);
    OkButton.Parent := Form;
    OkButton.Caption := 'Continue';
    OkButton.ModalResult := mrOk;
    OkButton.Default := True;
    OkButton.Cancel := True;
    OkButton.SetBounds(Form.ClientWidth - ScaleX(96), Form.ClientHeight - ScaleY(36), ScaleX(80), ScaleY(25));
    Form.ActiveControl := OkButton;
    Form.ShowModal();
    Result := Box.Checked;
  finally
    Form.Free();
  end;
end;

var
  RemoveEverything: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  FindRec: TFindRec;
  Hub: String;
begin
  if CurUninstallStep = usUninstall then
    RemoveEverything := not UninstallSilent and AskRemoveEverything();
  if (CurUninstallStep <> usPostUninstall) or not RemoveEverything then
    Exit;
  DelTree(ExpandConstant('{app}'), True, True, True);
  Hub := ExpandConstant('{%USERPROFILE}') + '\.cache\huggingface\hub\';
  if FindFirst(Hub + 'models--Systran--faster-whisper-*', FindRec) then
  try
    repeat
      DelTree(Hub + FindRec.Name, True, True, True);
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

[UninstallDelete]
; what ProfMute downloaded or wrote by itself. Kept: the log folder (the user's records), the settings and the
; edited lists. "Remove everything" in the uninstaller removes those too (see [Code]).
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\voice-models"
Type: filesandordirs; Name: "{app}\speak-models"
Type: filesandordirs; Name: "{app}\review"
Type: filesandordirs; Name: "{app}\speak_stubs\tn\__pycache__"
Type: filesandordirs; Name: "{app}\speak_stubs\tn\chinese\__pycache__"
Type: filesandordirs; Name: "{app}\speak_stubs\tn\english\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\voice_separation\__pycache__"
Type: filesandordirs; Name: "{app}\launcher\__pycache__"
Type: files; Name: "{app}\setup-log.txt"
