// ProfMute.exe - opens the ProfMute window. It is a launcher, not the program itself: it starts
// profmute_gui.py with the Python environment in this folder (.venv), without a console window.
// When that environment does not exist yet (first run on a new PC), it sets it up first.
//
// Rebuild (from the project folder, only needed after changing this file or the icon):
//   uv run python build_dist.py
// or by hand:
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe /optimize ^
//       /win32icon:profmute.ico /r:System.Windows.Forms.dll /out:ProfMute.exe launcher\ProfMute.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("ProfMute")]
[assembly: AssemblyProduct("ProfMute")]
[assembly: AssemblyDescription("Mutes profanity in a movie's audio track")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Launcher
{
    const string Title = "ProfMute";

    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");
        string gui = Path.Combine(dir, "profmute_gui.py");
        if (!File.Exists(gui))
        {
            MessageBox.Show("profmute_gui.py is missing.\n\nProfMute.exe has to stay in the ProfMute folder, next to it.",
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        if (!File.Exists(python) && !Setup(dir, python))
            return;
        var start = new ProcessStartInfo(python, "\"" + gui + "\"");
        start.WorkingDirectory = dir;
        start.UseShellExecute = false;
        Process.Start(start);
    }

    // First run: let uv download Python and the libraries into this folder.
    static bool Setup(string dir, string python)
    {
        string uv = Path.Combine(dir, "tools", "uv.exe");
        if (!File.Exists(uv))
            uv = FindOnPath("uv.exe");
        if (uv == null)
        {
            MessageBox.Show("ProfMute has not been set up yet, and the installer it uses (tools\\uv.exe) is missing.\n\n" +
                            "Unzip the whole ProfMute folder again, or install uv from https://docs.astral.sh/uv/ and start ProfMute again.",
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        if (MessageBox.Show("Welcome to ProfMute.\n\n" +
                            "Before its first run, ProfMute has to download Python and the speech recognition libraries " +
                            "into its own folder:\n\n" + dir + "\n\n" +
                            "That is about 2.2 GB and needs an internet connection. It takes several minutes and only happens once.\n\n" +
                            "Download now?",
                            Title + " - first-time setup", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK)
            return false;

        // A console window shows uv's progress; it stays open only if something went wrong.
        var setup = new ProcessStartInfo("cmd.exe",
            "/s /c \"title ProfMute first-time setup & echo Downloading Python and the libraries, about 2.2 GB. " +
            "This window closes by itself when it is done. & echo. & \"" + uv + "\" sync --frozen " +
            "|| (echo. & echo Setup did not finish. Check your internet connection, then start ProfMute again. & pause)\"");
        setup.WorkingDirectory = dir;
        setup.UseShellExecute = false;
        setup.EnvironmentVariables["UV_PYTHON_INSTALL_DIR"] = Path.Combine(dir, "python");   // keep Python in this folder too
        setup.EnvironmentVariables["UV_PYTHON_PREFERENCE"] = "only-managed";
        setup.EnvironmentVariables["UV_NO_CACHE"] = "1";                                      // no second copy left on the PC
        setup.EnvironmentVariables["UV_LINK_MODE"] = "copy";
        try
        {
            using (Process p = Process.Start(setup))
                p.WaitForExit();
        }
        catch (Exception e)
        {
            MessageBox.Show("Setup could not be started:\n\n" + e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        if (File.Exists(python))
            return true;
        MessageBox.Show("Setup did not finish, so ProfMute cannot start yet.\n\n" +
                        "Check your internet connection and that this folder can be written to " +
                        "(not inside Program Files), then start ProfMute again.",
                        Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
        return false;
    }

    static string FindOnPath(string name)
    {
        foreach (string folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            try
            {
                string candidate = Path.Combine(folder.Trim(), name);
                if (File.Exists(candidate))
                    return candidate;
            }
            catch (ArgumentException) { }   // a malformed PATH entry
        }
        return null;
    }
}
