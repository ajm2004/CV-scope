; CV-Scope setup for Windows (Inno Setup 7.1 or newer).
;
; Build:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
; build.ps1 builds the frontend, fetches uv.exe (checked against pins.json),
; draws the icon and wizard pictures, writes build\pins.iss and
; build\pins-code.iss from pins.json, and compiles this script into
; build\output\CV-Scope-Setup-Windows-x64.exe.
;
; What Setup does on the user's computer:
;  1. before installing anything, downloads the PyTorch build for the chosen
;     processor (CPU, or CUDA for an NVIDIA graphics card) from the PyTorch
;     index, with progress and an Abort button, and checks its SHA-256;
;  2. copies the application: backend source, built web interface, uv.exe;
;  3. installs a private Python with uv (no PATH or registry changes), creates
;     .venv and installs CV-Scope and its packages at the versions in
;     constraints.txt;
;  4. creates the database, then downloads the chosen models, the sample
;     videos and local vision models (these may fail without failing Setup);
;  5. adds the CV-Scope shortcut. It runs "pythonw -m pathscope.launcher",
;     which starts the server and opens it in the browser.
; A per-user installation: no administrator rights, and nothing outside the
; installation folder, the data folder and the Start menu is changed.
;
; Silent installs accept, besides the standard /DIR, /COMPONENTS and /TASKS:
;   /TORCH=auto|cpu|cu126|cu130   PyTorch build (default: chosen from the GPU)
;   /DATADIR="D:\CV-Scope data"    data folder (default %LOCALAPPDATA%\CV-Scope)
; Exit code 0: installed; 10: the core installation failed; 11: installed, but
; some optional downloads (models, samples, local vision models) failed.

#include "build\pins.iss"

#define AppName "CV-Scope"
#define AppId "FAF592A5-39B8-43E9-BD2B-585BDD90A4CB"
#define AppURL "https://github.com/ajm2004/CV-Scope"
#define Repo ".."
#define Launcher "-m pathscope.launcher"

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=CV-Scope contributors
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Apache License 2.0
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\CV-Scope
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern dynamic
SetupIconFile=build\cvscope.ico
; The same pictures in light and dark mode (without the DynamicDark lines, dark
; mode shows Inno Setup's own pictures)
#define WizardImages "build\wizard-large-202.png,build\wizard-large-336.png,build\wizard-large-430.png,build\wizard-large-534.png"
#define WizardSmallImages "build\wizard-small-58.png,build\wizard-small-97.png,build\wizard-small-124.png,build\wizard-small-159.png"
WizardImageFile={#WizardImages}
WizardImageFileDynamicDark={#WizardImages}
WizardSmallImageFile={#WizardSmallImages}
WizardSmallImageFileDynamicDark={#WizardSmallImages}
UninstallDisplayIcon={app}\cvscope.ico
UninstallDisplayName={#AppName}
OutputDir=build\output
OutputBaseFilename=CV-Scope-Setup-Windows-x64
Compression=lzma2/max
SolidCompression=yes
SetupLogging=yes
; The launcher holds this mutex: Setup and Uninstall ask to close CV-Scope first.
AppMutex=CV-Scope-Launcher
; RedirectionGuard protects elevated installers from junctions planted by other
; users. This one never elevates, and with it on, uv (started by Setup) cannot
; use the junction it creates for Python 3.11 (error 448), nor can Uninstall remove it.
RedirectionGuard=no
; Python, PyTorch for the CPU and the other packages; the GPU build needs more (checked before download)
ExtraDiskSpaceRequired=1500000000

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nSetup downloads what CV-Scope needs while it installs: a private copy of Python, PyTorch (0.1 GB, or about 2-2.6 GB for an NVIDIA graphics card) and the models you choose. Keep the computer connected to the internet.%n%nNothing has to be installed first, and no administrator rights are needed.
FinishedLabel=Setup has installed [name] on your computer.%n%nStart it any time with the CV-Scope shortcut: it starts CV-Scope and opens it in your web browser.

[Types]
Name: "recommended"; Description: "Recommended: the application, three YOLO11 detectors and the sample videos"
Name: "full"; Description: "All CV-Scope models"
Name: "minimal"; Description: "Minimal: the application only (add models later on the Models page)"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "app"; Description: "CV-Scope application with Python and PyTorch"; Types: recommended full minimal custom; Flags: fixed
Name: "detectors"; Description: "Object detectors (80 everyday object classes)"; Types: recommended full
Name: "detectors\yolo11n"; Description: "YOLO11n: fastest, good on any computer"; Types: recommended full; ExtraDiskSpaceRequired: 5600000
Name: "detectors\yolo11s"; Description: "YOLO11s: more accurate, still fast"; Types: recommended full; ExtraDiskSpaceRequired: 19200000
Name: "detectors\yolo11m"; Description: "YOLO11m: accurate, best with a graphics card"; Types: recommended full; ExtraDiskSpaceRequired: 40500000
Name: "detectors\yolo11l"; Description: "YOLO11l: very accurate, needs a graphics card"; Types: full; ExtraDiskSpaceRequired: 51200000
Name: "detectors\yolo11x"; Description: "YOLO11x: most accurate YOLO11, needs a graphics card"; Types: full; ExtraDiskSpaceRequired: 114400000
Name: "detectors\yolov8"; Description: "YOLOv8n, s and m: previous generation, for older studies"; Types: full; ExtraDiskSpaceRequired: 81000000
Name: "detectors\rtdetr"; Description: "RT-DETR-L and X: for crowded scenes, need a graphics card"; Types: full; ExtraDiskSpaceRequired: 192000000
Name: "detectors\onnx"; Description: "ONNX versions of YOLO11n, s and m (exported during Setup)"; Types: full; ExtraDiskSpaceRequired: 170000000
Name: "detectors\torchvision"; Description: "SSDLite and Faster R-CNN (torchvision, BSD licence)"; Types: full; ExtraDiskSpaceRequired: 254700000
Name: "tracking"; Description: "Appearance features for the BoT-SORT tracker"; Types: full; ExtraDiskSpaceRequired: 44700000
Name: "recognition"; Description: "Face and plate recognition models (work only with a licence)"; Types: full
Name: "recognition\face"; Description: "YuNet and SFace face models (MIT, Apache-2.0)"; Types: full; ExtraDiskSpaceRequired: 37100000
Name: "recognition\insightface"; Description: "SCRFD and ArcFace (non-commercial research use only)"; Types: full; ExtraDiskSpaceRequired: 457000000
Name: "recognition\plate"; Description: "Licence plate detectors and plate reading (MIT)"; Types: full; ExtraDiskSpaceRequired: 49200000
Name: "samples"; Description: "Sample videos (two short CC-BY-4.0 clips)"; Types: recommended full; ExtraDiskSpaceRequired: 11600000
Name: "extras"; Description: "Optional packages"; Types: recommended full
Name: "extras\claude"; Description: "Anthropic Claude for the Anomaly Assistant"; Types: recommended full; ExtraDiskSpaceRequired: 5000000
Name: "extras\postgres"; Description: "PostgreSQL database driver"; Types: full; ExtraDiskSpaceRequired: 10000000
Name: "localai"; Description: "Local vision model for the Anomaly Assistant (installs Ollama)"
Name: "localai\moondream"; Description: "moondream: small, runs on the processor"; ExtraDiskSpaceRequired: 1700000000
Name: "localai\qwen3b"; Description: "qwen2.5vl:3b: for graphics cards with 6-8 GB"; ExtraDiskSpaceRequired: 3200000000
Name: "localai\qwen7b"; Description: "qwen2.5vl:7b: for graphics cards with 12 GB or more"; ExtraDiskSpaceRequired: 6000000000

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; An update replaces the code instead of mixing old and new files (a stale
; migration would break the database upgrade).
Type: filesandordirs; Name: "{app}\backend\pathscope"
Type: filesandordirs; Name: "{app}\backend\alembic"
Type: filesandordirs; Name: "{app}\frontend\dist"

[Files]
Source: "build\tools\uv.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "constraints.txt"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "build\cvscope.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Repo}\backend\pyproject.toml"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "{#Repo}\backend\README.md"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "{#Repo}\backend\alembic.ini"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "{#Repo}\backend\alembic\*"; DestDir: "{app}\backend\alembic"; Excludes: "*.pyc"; Flags: recursesubdirs ignoreversion
Source: "{#Repo}\backend\pathscope\*"; DestDir: "{app}\backend\pathscope"; Excludes: "*.pyc"; Flags: recursesubdirs ignoreversion
Source: "{#Repo}\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: recursesubdirs ignoreversion
Source: "{#Repo}\samples\README.md"; DestDir: "{app}\samples"; Flags: ignoreversion
Source: "{#Repo}\samples\scenes\*"; DestDir: "{app}\samples\scenes"; Flags: ignoreversion
Source: "{#Repo}\samples\experiments\*"; DestDir: "{app}\samples\experiments"; Flags: ignoreversion
Source: "{#Repo}\scripts\download_samples.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#Repo}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Repo}\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\CV-Scope"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "{#Launcher}"; WorkingDir: "{app}"; IconFilename: "{app}\cvscope.ico"; Comment: "Start CV-Scope and open it in the web browser"; AppUserModelID: "CVScope.Launcher"
Name: "{autodesktop}\CV-Scope"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "{#Launcher}"; WorkingDir: "{app}"; IconFilename: "{app}\cvscope.ico"; Comment: "Start CV-Scope and open it in the web browser"; AppUserModelID: "CVScope.Launcher"; Tasks: desktopicon

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "{#Launcher}"; WorkingDir: "{app}"; Description: "Start CV-Scope now"; Flags: postinstall nowait skipifsilent; Check: SetupSucceeded

[UninstallDelete]
; Created by Setup after the files were copied (Python, packages, downloads)
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\samples"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\.env"
Type: dirifempty; Name: "{app}"

[Code]
const
  CUDA12_MIN_DRIVER = 528;  { CUDA 12.x builds run on driver 527.41 and newer }
  CUDA13_MIN_DRIVER = 580;  { CUDA 13.0 needs the R580 driver branch }
  OTHER_PACKAGES_MB = 400;  { Python and every package besides PyTorch }
  UNINSTALL_KEY = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppId}}_is1';

var
  AccelPage: TInputOptionWizardPage;
  DataPage: TInputDirWizardPage;
  DownloadPage: TDownloadWizardPage;
  GpuName, GpuDriver, GpuVariant, GpuNote, ForcedTorch: String;
  GpuCC10, GpuDriverMajor, GpuMemMiB: Integer;
  InstallLog, LastLine, CudaLine, Warnings, FailureText, Collected: String;
  StepHi: Integer;
  SetupFailed, OptionalFailed, TorchInTmp: Boolean;
  UninstallDataDir: String;

#include "build\pins-code.iss"

function SetEnvironmentVariable(lpName, lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

{ ------------------------------------------------------------------ helpers }

function SizeText(Bytes: Int64): String;
var
  Tenths: Int64;
begin
  if Bytes >= 1000000000 then begin
    Tenths := (Bytes + 50000000) div 100000000;
    Result := IntToStr(Tenths div 10) + '.' + IntToStr(Tenths mod 10) + ' GB';
  end else
    Result := IntToStr((Bytes + 500000) div 1000000) + ' MB';
end;

function LeadingInt(const S: String): Integer;
var
  I: Integer;
  Digits: String;
begin
  Digits := '';
  for I := 1 to Length(S) do begin
    if (S[I] < '0') or (S[I] > '9') then
      Break;
    Digits := Digits + S[I];
  end;
  Result := StrToIntDef(Digits, 0);
end;

function Quote(const S: String): String;
begin
  Result := '"' + S + '"';
end;

procedure AppendLog(const S: String);
var
  Line: TArrayOfString;
begin
  Log(S);
  if InstallLog <> '' then begin
    SetArrayLength(Line, 1);
    Line[0] := S;
    SaveStringsToUTF8FileWithoutBOM(InstallLog, Line, True);
  end;
end;

function DefaultDataDir: String;
begin
  Result := ExpandConstant('{localappdata}\CV-Scope');
end;

{ ------------------------------------------------------------------ graphics card }

procedure DetectGpu;
var
  Exe, CC: String;
  Output: TExecOutput;
  ResultCode, Dot: Integer;
  Parts: TArrayOfString;
begin
  GpuName := '';
  Exe := ExpandConstant('{sys}\nvidia-smi.exe');
  if not FileExists(Exe) then
    Exe := ExpandConstant('{commonpf64}\NVIDIA Corporation\NVSMI\nvidia-smi.exe');
  if not FileExists(Exe) then
    Exit;
  try
    if not ExecAndCaptureOutput(Exe, '--query-gpu=name,compute_cap,driver_version,memory.total --format=csv,noheader,nounits',
                                '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode, Output) then
      Exit;
  except
    Log('nvidia-smi failed: ' + GetExceptionMessage);
    Exit;
  end;
  if (ResultCode <> 0) or (GetArrayLength(Output.StdOut) = 0) then
    Exit;
  Log('nvidia-smi: ' + Output.StdOut[0]);
  Parts := StringSplit(Output.StdOut[0], [','], stAll);
  if GetArrayLength(Parts) < 4 then
    Exit;
  GpuName := Trim(Parts[0]);
  CC := Trim(Parts[1]);
  Dot := Pos('.', CC);
  if Dot > 0 then
    GpuCC10 := StrToIntDef(Copy(CC, 1, Dot - 1), 0) * 10 + StrToIntDef(Copy(CC, Dot + 1, 1), 0)
  else
    GpuCC10 := StrToIntDef(CC, 0) * 10;
  GpuDriver := Trim(Parts[2]);
  GpuDriverMajor := LeadingInt(GpuDriver);
  GpuMemMiB := StrToIntDef(Trim(Parts[3]), 0);
end;

{ Chooses the PyTorch build for the card: CUDA 12.6 covers Maxwell to Ada
  (GTX 900 to RTX 40 series), CUDA 13.0 is needed for Blackwell (RTX 50). }
procedure ChooseGpuVariant;
var
  MinDriver: Integer;
begin
  GpuVariant := '';
  GpuNote := '';
  if GpuName = '' then begin
    GpuNote := 'No NVIDIA graphics card was found, so CV-Scope will run its models on the processor. That works on any computer; detection is slower.';
    Exit;
  end;
  if GpuCC10 < 50 then begin
    GpuNote := 'Found ' + GpuName + ', which is too old for current PyTorch builds. CV-Scope will run its models on the processor.';
    Exit;
  end;
  if GpuCC10 >= 100 then begin
    GpuVariant := 'cu130';
    MinDriver := CUDA13_MIN_DRIVER;
  end else begin
    GpuVariant := 'cu126';
    MinDriver := CUDA12_MIN_DRIVER;
  end;
  GpuNote := 'Found ' + GpuName + ' (' + IntToStr((GpuMemMiB + 512) div 1024) + ' GB, driver ' + GpuDriver + '). Using it makes detection several times faster.';
  if GpuDriverMajor < MinDriver then
    GpuNote := GpuNote + #13#10#13#10 + 'Its driver is too old for PyTorch: install NVIDIA driver ' + IntToStr(MinDriver) + ' or newer (nvidia.com/drivers), then choose the graphics card here. Until then, use the processor.';
end;

function GpuUsable: Boolean;
begin
  Result := (GpuVariant <> '') and ((GpuDriverMajor >= CUDA13_MIN_DRIVER) or ((GpuVariant = 'cu126') and (GpuDriverMajor >= CUDA12_MIN_DRIVER)));
end;

function TorchVariant: String;
begin
  if (ForcedTorch = 'cpu') or (ForcedTorch = 'cu126') or (ForcedTorch = 'cu130') then
    Result := ForcedTorch
  else if (AccelPage <> nil) and AccelPage.Values[0] and (GpuVariant <> '') then
    Result := GpuVariant
  else
    Result := 'cpu';
end;

function VariantLabel(const V: String): String;
begin
  if V = 'cu126' then
    Result := 'CUDA 12.6 (NVIDIA graphics card)'
  else if V = 'cu130' then
    Result := 'CUDA 13.0 (NVIDIA graphics card)'
  else
    Result := 'CPU';
end;

{ ------------------------------------------------------------------ components }

procedure AddIds(const Component, Ids: String);
begin
  if WizardIsComponentSelected(Component) then
    Collected := Trim(Collected + ' ' + Ids);
end;

{ Model ids of the CV-Scope catalog (cvscope models list) per component.
  backend/tests/test_installer.py checks them against the catalog. }
function SelectedModels: String;
begin
  Collected := '';
  AddIds('detectors\yolo11n', 'yolo11n');
  AddIds('detectors\yolo11s', 'yolo11s');
  AddIds('detectors\yolo11m', 'yolo11m');
  AddIds('detectors\yolo11l', 'yolo11l');
  AddIds('detectors\yolo11x', 'yolo11x');
  AddIds('detectors\yolov8', 'yolov8n yolov8s yolov8m');
  AddIds('detectors\rtdetr', 'rtdetr-l rtdetr-x');
  AddIds('detectors\onnx', 'yolo11n-onnx yolo11s-onnx yolo11m-onnx');
  AddIds('detectors\torchvision', 'tv-ssdlite320 tv-fasterrcnn-mobilenet tv-fasterrcnn-r50v2');
  AddIds('tracking', 'appearance-resnet18');
  AddIds('recognition\face', 'face-det-yunet face-emb-sface');
  AddIds('recognition\insightface', 'face-det-scrfd-10g face-emb-arcface-r50');
  AddIds('recognition\plate', 'plate-det-yolov9t-384 plate-det-yolov9t-640 plate-det-yolov9s-608 plate-ocr-cct-s-v2 plate-ocr-cct-xs-v1');
  Result := Collected;
end;

function SelectedLocalModels: String;
begin
  Collected := '';
  AddIds('localai\moondream', 'moondream');
  AddIds('localai\qwen3b', 'qwen2.5vl:3b');
  AddIds('localai\qwen7b', 'qwen2.5vl:7b');
  Result := Collected;
end;

function SelectedExtras: String;
begin
  Result := 'ultralytics,onnx-cpu,export';
  if WizardIsComponentSelected('extras\claude') then
    Result := Result + ',llm';
  if WizardIsComponentSelected('extras\postgres') then
    Result := Result + ',postgres';
end;

{ Approximate download in MB of the chosen models, samples and local models }
function OptionalDownloadMB: Integer;
begin
  Result := 0;
  if WizardIsComponentSelected('detectors\yolo11n') then Result := Result + 6;
  if WizardIsComponentSelected('detectors\yolo11s') then Result := Result + 19;
  if WizardIsComponentSelected('detectors\yolo11m') then Result := Result + 41;
  if WizardIsComponentSelected('detectors\yolo11l') then Result := Result + 51;
  if WizardIsComponentSelected('detectors\yolo11x') then Result := Result + 114;
  if WizardIsComponentSelected('detectors\yolov8') then Result := Result + 81;
  if WizardIsComponentSelected('detectors\rtdetr') then Result := Result + 192;
  if WizardIsComponentSelected('detectors\onnx') then Result := Result + 90;
  if WizardIsComponentSelected('detectors\torchvision') then Result := Result + 255;
  if WizardIsComponentSelected('tracking') then Result := Result + 45;
  if WizardIsComponentSelected('recognition\face') then Result := Result + 37;
  if WizardIsComponentSelected('recognition\insightface') then Result := Result + 275;
  if WizardIsComponentSelected('recognition\plate') then Result := Result + 50;
  if WizardIsComponentSelected('samples') then Result := Result + 12;
  if SelectedLocalModels <> '' then Result := Result + 1200;
  if WizardIsComponentSelected('localai\moondream') then Result := Result + 1700;
  if WizardIsComponentSelected('localai\qwen3b') then Result := Result + 3200;
  if WizardIsComponentSelected('localai\qwen7b') then Result := Result + 6000;
end;

function TorchDownloadBytes: Int64;
begin
  Result := StrToInt64(Pin(TorchVariant + '.torch.size')) + StrToInt64(Pin(TorchVariant + '.torchvision.size'));
end;

function AppDir: String;
begin
  Result := WizardDirValue;
end;

function DistInfo(const Package, Version: String): String;
begin
  Result := AppDir + '\.venv\Lib\site-packages\' + Package + '-' + Version + '+' + TorchVariant + '.dist-info';
end;

{ An update keeps the PyTorch build that is already installed }
function TorchInstalled: Boolean;
begin
  Result := DirExists(DistInfo('torch', '{#TorchVersion}')) and DirExists(DistInfo('torchvision', '{#TorchvisionVersion}'));
end;

{ ------------------------------------------------------------------ data folder }

function EnvPath(const Dir: String): String;
begin
  { python-dotenv: single quotes keep spaces and #; forward slashes avoid escapes }
  Result := Dir;
  StringChangeEx(Result, '\', '/', True);
  StringChangeEx(Result, '''', '\''', True);
  Result := '''' + Result + '''';
end;

procedure WriteEnvFile(const DataDir: String);
var
  Lines, Kept: TArrayOfString;
  I, N: Integer;
  Path: String;
begin
  Path := ExpandConstant('{app}\.env');
  N := 0;
  if LoadStringsFromFile(Path, Lines) then begin
    SetArrayLength(Kept, GetArrayLength(Lines) + 1);
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos('PATHSCOPE_DATA_DIR=', Trim(Lines[I])) <> 1 then begin
        Kept[N] := Lines[I];
        N := N + 1;
      end;
  end else begin
    SetArrayLength(Kept, 4);
    Kept[0] := '# CV-Scope settings for this installation (see docs/installation.md, "Configuration").';
    Kept[1] := '# Setup writes PATHSCOPE_DATA_DIR and keeps every other line when it updates CV-Scope.';
    N := 2;
  end;
  Kept[N] := 'PATHSCOPE_DATA_DIR=' + EnvPath(DataDir);
  SetArrayLength(Kept, N + 1);
  { no byte order mark: python-dotenv would read it as part of the first line }
  SaveStringsToUTF8FileWithoutBOM(Path, Kept, False);
end;

function IsSyncedFolder(const Dir: String): Boolean;
var
  U: String;
begin
  U := Uppercase(AddBackslash(Dir));
  Result := (Pos('\ONEDRIVE', U) > 0) or (Pos('\DROPBOX\', U) > 0) or (Pos('\GOOGLE DRIVE\', U) > 0) or (Pos('\ICLOUDDRIVE\', U) > 0);
  if (not Result) and (GetEnv('OneDrive') <> '') then
    Result := Pos(Uppercase(AddBackslash(GetEnv('OneDrive'))), U) = 1;
end;

{ ------------------------------------------------------------------ wizard }

function InitializeSetup: Boolean;
begin
  ForcedTorch := Lowercase(ExpandConstant('{param:TORCH|auto}'));
  DetectGpu;
  ChooseGpuVariant;
  Result := True;
end;

procedure InitializeWizard;
var
  Previous: String;
begin
  AccelPage := CreateInputOptionPage(wpSelectDir, 'Graphics card', 'Choose where CV-Scope runs its detection models.', GpuNote, True, False);
  if GpuVariant <> '' then
    AccelPage.Add('Use the NVIDIA graphics card (recommended): about ' + SizeText(StrToInt64(Pin(GpuVariant + '.torch.size'))) + ' download')
  else
    AccelPage.Add('Use an NVIDIA graphics card: not available on this computer');
  AccelPage.Add('Use the processor only (CPU): about ' + SizeText(StrToInt64(Pin('cpu.torch.size'))) + ' download, slower detection');
  Previous := GetPreviousData('Torch', '');
  if GpuUsable and (Previous <> 'cpu') then
    AccelPage.SelectedValueIndex := 0
  else
    AccelPage.SelectedValueIndex := 1;
  if GpuVariant = '' then
    AccelPage.CheckListBox.ItemEnabled[0] := False;

  DataPage := CreateInputDirPage(wpSelectComponents, 'Data folder', 'Where should CV-Scope keep its data?',
    'CV-Scope keeps its database, videos, recordings, exports and downloaded models in this folder. ' +
    'It stays when you update or uninstall CV-Scope, unless you ask to delete it then.' + #13#10#13#10 +
    'Choose a drive with room for recordings. Avoid folders that OneDrive or Dropbox synchronise.', False, '');
  DataPage.Add('');
  Previous := ExpandConstant('{param:DATADIR|}');
  if Previous = '' then
    Previous := GetPreviousData('DataDir', DefaultDataDir);
  DataPage.Values[0] := Previous;

  DownloadPage := CreateDownloadPage('Downloading PyTorch', 'Setup downloads PyTorch before it installs anything. This can take a while.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'Torch', TorchVariant);
  SetPreviousData(PreviousDataKey, 'DataDir', DataPage.Values[0]);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Download: Int64;
begin
  Download := OTHER_PACKAGES_MB + OptionalDownloadMB;
  Download := Download * 1000000;
  if not TorchInstalled then
    Download := Download + TorchDownloadBytes;
  Result := '';
  if MemoDirInfo <> '' then  { empty on updates, which skip the folder page }
    Result := MemoDirInfo + NewLine + NewLine;
  Result := Result + 'Data folder:' + NewLine + Space + DataPage.Values[0] + NewLine + NewLine +
    'Runs models on:' + NewLine + Space + 'PyTorch {#TorchVersion}, ' + VariantLabel(TorchVariant) + NewLine + NewLine;
  if MemoTypeInfo <> '' then
    Result := Result + MemoTypeInfo + NewLine + NewLine;
  if MemoComponentsInfo <> '' then
    Result := Result + MemoComponentsInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + MemoTasksInfo + NewLine + NewLine;
  Result := Result + 'Downloads:' + NewLine + Space + 'About ' + SizeText(Download) +
    ' from pytorch.org, pypi.org, github.com and the model hosts';
end;

function CheckFreeSpace: Boolean;
var
  Free, Total, Need, NeedTmp: Int64;
  Drive: String;
begin
  Result := True;
  { unpacked PyTorch (about 1.7 times the wheel; CUDA 12.6: 4.0 GB), the other
    packages unpacked and in uv's cache while installing, models }
  Need := OTHER_PACKAGES_MB * 4 + OptionalDownloadMB;
  Need := Need * 1000000 + (TorchDownloadBytes * 17) div 10;
  Drive := ExtractFileDrive(AppDir);
  if GetSpaceOnDisk64(Drive + '\', Free, Total) and (Free < Need) then begin
    SuppressibleMsgBox(Format('CV-Scope needs about %s of free space on %s, which has %s.' + #13#10#13#10 +
      'Free some space or choose another installation folder.', [SizeText(Need), Drive, SizeText(Free)]), mbError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  NeedTmp := TorchDownloadBytes + 200000000;
  if (not TorchInstalled) and GetSpaceOnDisk64(ExpandConstant('{tmp}'), Free, Total) and (Free < NeedTmp) then begin
    { a continuation line must not start with "[": the compiler reads it as a section }
    SuppressibleMsgBox(Format('Setup downloads PyTorch to the temporary folder first and needs %s free there (%s), which has %s.', [
      SizeText(NeedTmp), ExtractFileDrive(ExpandConstant('{tmp}')), SizeText(Free)]), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function DownloadTorch: Boolean;
var
  V: String;
begin
  Result := True;
  TorchInTmp := False;
  if TorchInstalled then begin
    Log('PyTorch {#TorchVersion}+' + TorchVariant + ' is already installed; not downloading it again.');
    Exit;
  end;
  V := TorchVariant;
  DownloadPage.Description := 'Setup downloads PyTorch for ' + VariantLabel(V) + ' (' + SizeText(TorchDownloadBytes) + ') before it installs anything. This can take a while.';
  DownloadPage.Clear;
  DownloadPage.Add(Pin(V + '.torch.url'), Pin(V + '.torch.file'), Pin(V + '.torch.sha256'));
  DownloadPage.Add(Pin(V + '.torchvision.url'), Pin(V + '.torchvision.file'), Pin(V + '.torchvision.sha256'));
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      TorchInTmp := True;
    except
      if DownloadPage.AbortedByUser then
        Log('PyTorch download aborted by the user.')
      else
        SuppressibleMsgBox('PyTorch could not be downloaded: ' + DownloadPage.LastBaseNameOrUrl + ': ' + GetExceptionMessage + #13#10#13#10 +
          'Check the internet connection and click Install to try again.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID = DataPage.ID then begin
    Dir := Trim(DataPage.Values[0]);
    if not PathIsRooted(Dir) then begin
      SuppressibleMsgBox('Choose a full folder path, for example ' + DefaultDataDir + '.', mbError, MB_OK, IDOK);
      Result := False;
    end else if IsSyncedFolder(Dir) then
      Result := SuppressibleMsgBox('This folder is synchronised with the cloud. Synchronising the database while CV-Scope uses it can damage it, ' +
        'and recordings and models would fill the cloud storage.' + #13#10#13#10 + 'Use this folder anyway?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  end else if CurPageID = wpReady then
    Result := CheckFreeSpace and DownloadTorch;
end;

{ ------------------------------------------------------------------ installation steps }

procedure SetStepProgress(Permille: Integer);
begin
  WizardForm.ProgressGauge.Max := 1000;
  WizardForm.ProgressGauge.Position := Permille;
end;

{ Each line of a step's output is logged, shown under the progress bar and
  moves the bar a twentieth of the way to the end of the step. }
procedure StepOutput(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
begin
  AppendLog(S);
  Line := Trim(S);
  if (Line = '') or Error then
    Exit;
  LastLine := Line;
  if Pos('CUDA:', Line) = 1 then
    CudaLine := Line;
  WizardForm.FilenameLabel.Caption := Copy(Line, 1, 110);
  if WizardForm.ProgressGauge.Position < StepHi - 1 then
    SetStepProgress(WizardForm.ProgressGauge.Position + (StepHi - WizardForm.ProgressGauge.Position + 19) div 20);
end;

function RunStep(const Title, Filename, Params: String; Lo, Hi: Integer): Boolean;
var
  ResultCode: Integer;
begin
  StepHi := Hi;
  LastLine := '';
  WizardForm.StatusLabel.Caption := Title;
  WizardForm.FilenameLabel.Caption := '';
  SetStepProgress(Lo);
  AppendLog('');
  AppendLog('== ' + Title);
  AppendLog('> ' + Quote(Filename) + ' ' + Params);
  ResultCode := -1;
  try
    Result := ExecAndLogOutput(Filename, Params, ExpandConstant('{app}'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode, @StepOutput) and (ResultCode = 0);
  except
    AppendLog('Could not run the step: ' + GetExceptionMessage);
    Result := False;
  end;
  if Result then
    SetStepProgress(Hi)
  else
    AppendLog(Format('Step failed with exit code %d', [ResultCode]));
end;

{ Steps without which CV-Scope cannot run: offered again after a failure }
function RunCoreStep(const Title, Filename, Params: String; Lo, Hi: Integer): Boolean;
begin
  repeat
    Result := RunStep(Title, Filename, Params, Lo, Hi);
    if Result then
      Exit;
  until SuppressibleMsgBox(Title + #13#10#13#10 + 'This step did not finish. ' + LastLine + #13#10#13#10 +
    'Check the internet connection and click Retry. Details are in ' + InstallLog + '.', mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY;
  FailureText := Title + ' did not finish. ' + LastLine;
end;

procedure OptionalStep(const Title, Filename, Params, Warning: String; Lo, Hi: Integer);
begin
  if not RunStep(Title, Filename, Params, Lo, Hi) then begin
    OptionalFailed := True;
    Warnings := Warnings + #13#10 + '- ' + Warning;
  end;
end;

procedure SetEnv(const Name, Value: String);
begin
  SetEnvironmentVariable(Name, Value);
end;

procedure RunSetupSteps;
var
  App, Uv, Py, Torch, Extra, Models, LocalModels: String;
  Ok: Boolean;
begin
  App := ExpandConstant('{app}');
  Uv := App + '\tools\uv.exe';
  Py := App + '\.venv\Scripts\python.exe';
  ForceDirectories(App + '\logs');
  InstallLog := App + '\logs\install.log';
  AppendLog('CV-Scope {#AppVersion} setup, ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':'));
  AppendLog('PyTorch build: ' + TorchVariant + '; GPU: ' + GpuName + ' ' + GpuDriver + '; data folder: ' + DataPage.Values[0]);

  { uv and Python: everything stays inside the installation folder }
  SetEnv('UV_PYTHON_INSTALL_DIR', App + '\runtime\python');
  SetEnv('UV_CACHE_DIR', App + '\runtime\cache');
  SetEnv('UV_NO_CONFIG', '1');
  SetEnv('UV_NO_PROGRESS', '1');
  SetEnv('UV_SYSTEM_CERTS', '1');
  SetEnv('NO_COLOR', '1');
  SetEnv('PYTHONUTF8', '1');
  SetEnv('PYTHONIOENCODING', 'utf-8');
  SetEnv('PYTHONUNBUFFERED', '1');
  SetEnv('PIP_DISABLE_PIP_VERSION_CHECK', '1');
  WriteEnvFile(DataPage.Values[0]);

  if TorchInTmp then
    Torch := Quote(ExpandConstant('{tmp}\') + Pin(TorchVariant + '.torch.file')) + ' ' + Quote(ExpandConstant('{tmp}\') + Pin(TorchVariant + '.torchvision.file'))
  else
    Torch := 'torch=={#TorchVersion} torchvision=={#TorchvisionVersion}';
  Extra := '';
  if WizardIsComponentSelected('detectors\onnx') then
    Extra := ' onnx onnxslim';

  Ok := RunCoreStep('Installing Python {#PythonVersion}...', Uv, 'python install {#PythonVersion} --no-bin --no-registry', 0, 40);
  if Ok then
    Ok := RunCoreStep('Creating the Python environment...', Uv, 'venv ' + Quote(App + '\.venv') + ' --python {#PythonVersion} --managed-python --seed --allow-existing', 40, 70);
  if Ok then
    Ok := RunCoreStep('Installing PyTorch and the CV-Scope packages (a few minutes)...', Uv,
      'pip install --python ' + Quote(Py) + ' --torch-backend ' + TorchVariant + ' -c ' + Quote(App + '\tools\constraints.txt') + ' ' +
      Torch + ' -e ' + Quote(App + '\backend[' + SelectedExtras + ']') + Extra, 70, 600);
  if Ok then
    Ok := RunCoreStep('Preparing the database...', Py, '-m pathscope.cli migrate', 600, 630);
  if not Ok then begin
    SetupFailed := True;
    Exit;
  end;

  Models := SelectedModels;
  if Models <> '' then
    OptionalStep('Downloading the detection models...', Py, '-m pathscope.cli models install ' + Models,
      'Some models could not be downloaded. Install them later on the Models page.', 630, 860);
  if WizardIsComponentSelected('samples') then
    OptionalStep('Downloading the sample videos...', Py, Quote(App + '\scripts\download_samples.py'),
      'The sample videos could not be downloaded.', 860, 890);
  LocalModels := SelectedLocalModels;
  if LocalModels <> '' then
    OptionalStep('Installing Ollama and the local vision models (large download)...', Py, '-m pathscope.cli anomaly setup-local ' + LocalModels,
      'The local vision model was not set up. Set it up later in the Anomaly Assistant settings.', 890, 980);
  RunStep('Checking the hardware...', Py, '-m pathscope.cli hardware', 980, 1000);
  if (TorchVariant <> 'cpu') and (Pos('CUDA:    available', CudaLine) <> 1) then begin
    OptionalFailed := True;
    Warnings := Warnings + #13#10 + '- PyTorch cannot use the graphics card yet, so CV-Scope runs on the processor. Update the NVIDIA driver and restart the computer.';
  end;
  DelTree(App + '\runtime\cache', True, True, True);
end;

procedure DeleteShortcuts;
begin
  DeleteFile(ExpandConstant('{autoprograms}\CV-Scope.lnk'));
  DeleteFile(ExpandConstant('{autodesktop}\CV-Scope.lnk'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    RunSetupSteps;
    if SetupFailed then
      DeleteShortcuts;
  end;
end;

function SetupSucceeded: Boolean;
begin
  Result := not SetupFailed;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    if SetupFailed then begin
      WizardForm.FinishedHeadingLabel.Caption := 'CV-Scope is not ready yet';
      WizardForm.FinishedLabel.Caption := FailureText + #13#10#13#10 +
        'Run this Setup again to finish the installation; it continues where it stopped. The details are in ' + InstallLog + '.';
    end else if OptionalFailed then
      WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + 'Some parts need attention:' + Warnings;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if SetupFailed then
    Result := 10
  else if OptionalFailed then
    Result := 11
  else
    Result := 0;
end;

{ ------------------------------------------------------------------ uninstall }

function LooksLikeDataFolder(const Dir: String): Boolean;
begin
  Result := (Length(Dir) > 8) and DirExists(Dir) and
    (FileExists(Dir + '\pathscope.db') or DirExists(Dir + '\models') or DirExists(Dir + '\recordings')) and
    (CompareText(RemoveBackslash(Dir), RemoveBackslash(ExpandConstant('{%USERPROFILE}'))) <> 0) and
    (CompareText(RemoveBackslash(Dir), RemoveBackslash(ExpandConstant('{userdocs}'))) <> 0) and
    (CompareText(RemoveBackslash(Dir), RemoveBackslash(ExpandConstant('{userdesktop}'))) <> 0) and
    (CompareText(RemoveBackslash(Dir), RemoveBackslash(ExpandConstant('{localappdata}'))) <> 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if not RegQueryStringValue(HKCU, UNINSTALL_KEY, 'Inno Setup CodeFile: DataDir', UninstallDataDir) then
      UninstallDataDir := DefaultDataDir;
  end else if CurUninstallStep = usPostUninstall then begin
    if LooksLikeDataFolder(UninstallDataDir) then
      if SuppressibleMsgBox('Also delete your CV-Scope data?' + #13#10#13#10 + UninstallDataDir + #13#10#13#10 +
        'It holds your projects, recordings, exports and downloaded models. Choose No to keep it for a later installation.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
        DelTree(UninstallDataDir, True, True, True);
  end;
end;
