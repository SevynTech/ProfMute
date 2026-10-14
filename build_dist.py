"""Build what gets shared:  dist\\ProfMute\\ (the program folder), dist\\ProfMute-<version>.zip (that
folder zipped) and dist\\ProfMute-Setup-<version>.exe (an installer for it; needs Inno Setup 6).

Usage (from the project folder):  uv run python build_dist.py

Only the files listed below go in. Nothing personal can ride along: no movies, logs, settings or
Python environment, and the build stops if your Windows user folder (or any word listed in an
optional .private-terms.txt, one per line) shows up anywhere in the package.
"""
import os, shutil, subprocess, sys, zipfile
from pathlib import Path

import profmute

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
APP = DIST / "ProfMute"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")

COPY = ["profmute.py", "profmute_gui.py", "profmute.ico", "pyproject.toml", "uv.lock",
        "README.md", "CHANGELOG.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
        "voice_separation/__init__.py", "voice_separation/attend.py", "voice_separation/bs_roformer.py",
        "voice_separation/mel_band_roformer.py", "voice_separation/LICENSE",
        "launcher/ProfMute.cs", "launcher/make_icon.py",
        "licenses/uv-LICENSE-MIT.txt", "licenses/uv-LICENSE-APACHE.txt"]


def build_launcher():
    if not (HERE / "profmute.ico").is_file():
        subprocess.run([sys.executable, str(HERE / "launcher" / "make_icon.py")], check=True)
    if not CSC.is_file():
        if not (HERE / "ProfMute.exe").is_file():
            sys.exit(f"cannot build ProfMute.exe: {CSC} not found")
        return print("  C# compiler not found, keeping the existing ProfMute.exe")
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/optimize", "/win32icon:profmute.ico",
                    "/r:System.Windows.Forms.dll", "/out:ProfMute.exe", r"launcher\ProfMute.cs"], cwd=HERE, check=True)


def build_installer():
    """dist\\ProfMute-Setup-<version>.exe, made by Inno Setup from the files in dist\\ProfMute."""
    places = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
              Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"), Path(r"C:\Program Files\Inno Setup 6\ISCC.exe")]
    iscc = next((p for p in places if p.is_file()), None) or shutil.which("ISCC")
    if not iscc:
        print("  Inno Setup not found, so no installer was built (winget install --id JRSoftware.InnoSetup -e)")
        return None
    subprocess.run([str(iscc), "/Qp", f"/DAppVersion={profmute.__version__}", str(HERE / "installer" / "ProfMute.iss")],
                   check=True)
    return DIST / f"ProfMute-Setup-{profmute.__version__}.exe"


def private_terms():
    home = str(Path.home())
    terms = {home, home.replace("\\", "/"), home.replace("\\", "\\\\"),
             "Users\\" + Path.home().name, "Users/" + Path.home().name}
    extra = HERE / ".private-terms.txt"
    if extra.is_file():
        terms |= {line.strip() for line in extra.read_text(encoding="utf-8").splitlines() if line.strip()}
    return sorted(terms)


def leaks(folder):
    found = []
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        data = f.read_bytes().lower()
        for term in private_terms():
            if term.lower().encode("utf-8") in data or term.lower().encode("utf-16-le") in data:
                found.append(f"{f.relative_to(folder)}: contains {term!r}")
    return found


def main():
    print("Building ProfMute", profmute.__version__)
    build_launcher()
    if APP.exists():
        shutil.rmtree(APP)
    for name in COPY + ["ProfMute.exe"]:
        target = APP / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / name, target)
    # the editable lists ship as their defaults, whatever this PC's own copies say
    (APP / "words.txt").write_text(profmute.DEFAULT_WORDS, encoding="utf-8", newline="\r\n")
    (APP / "models.txt").write_text(profmute.DEFAULT_MODELS, encoding="utf-8", newline="\r\n")
    (APP / "voice-models.txt").write_text(profmute.DEFAULT_VOICE_MODELS, encoding="utf-8", newline="\r\n")
    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv.exe not found on this PC; it is needed in the package for first-time setup")
    (APP / "tools").mkdir()
    shutil.copy2(uv, APP / "tools" / "uv.exe")

    problems = leaks(APP)
    if problems:
        sys.exit("NOT SHAREABLE - personal information found in the package:\n  " + "\n  ".join(problems))

    archive = DIST / f"ProfMute-{profmute.__version__}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(p for p in APP.rglob("*") if p.is_file()):
            z.write(f, Path("ProfMute") / f.relative_to(APP))
    total = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file())
    print(f"  {APP}  ({total / 1e6:.0f} MB, {sum(1 for p in APP.rglob('*') if p.is_file())} files)")
    print(f"  {archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
    installer = build_installer()
    if installer:
        data = installer.read_bytes().lower()
        found = [t for t in private_terms() if t.lower().encode() in data or t.lower().encode("utf-16-le") in data]
        if found:
            installer.unlink()
            sys.exit(f"NOT SHAREABLE - the installer contains {found}")
        print(f"  {installer}  ({installer.stat().st_size / 1e6:.0f} MB)")
    print("  nothing personal found. Ready to share.")


if __name__ == "__main__":
    main()
