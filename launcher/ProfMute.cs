// ProfMute.exe - opens the ProfMute window. It is a launcher, not the program itself: it starts
// profmute_gui.py with the Python environment in this folder (.venv), without a console window.
// When that environment does not exist yet (first run on a new PC), it sets it up first.
//
// "ProfMute.exe --setup" only does that first-time download, without asking and without opening
// the window. The installer uses it, so ProfMute is ready the first time it is opened.
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
[assembly: AssemblyVersion("1.4.0.0")]

static class Launcher
{
    const string Title = "ProfMute";

    [STAThread]
    static int Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");
        string gui = Path.Combine(dir, "profmute_gui.py");
        bool setupOnly = args.Length > 0 && args[0] == "--setup";
        if (setupOnly)
            return Ready(dir, python) || Setup(dir, python, false) ? 0 : 1;
        if (!File.Exists(gui))
        {
            MessageBox.Show("profmute_gui.py is missing.\n\nProfMute.exe has to stay in the ProfMute folder, next to it.",
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        if (!Ready(dir, python) && !Setup(dir, python, true))
            return 1;
        var start = new ProcessStartInfo(python, "\"" + gui + "\"");
        start.WorkingDirectory = dir;
        start.UseShellExecute = false;
        Process.Start(start);
        return 0;
    }

    // Set up and complete? In a packaged copy (one that brings its own uv) a marker file says the
    // download finished; without it a half-finished download would look like a working install.
    static bool Ready(string dir, string python)
    {
        if (!File.Exists(python))
            return false;
        return File.Exists(Marker(dir)) || !File.Exists(Path.Combine(dir, "tools", "uv.exe"));
    }

    static string Marker(string dir)
    {
        return Path.Combine(dir, ".venv", "profmute-ready");
    }

    // First run: let uv download Python and the libraries into this folder.
    static bool Setup(string dir, string python, bool ask)
    {
        string uv = Path.Combine(dir, "tools", "uv.exe");
        if (!File.Exists(uv))
            uv = FindOnPath("uv.exe");
        if (uv == null)
        {
            if (ask)
                MessageBox.Show("ProfMute has not been set up yet, and the installer it uses (tools\\uv.exe) is missing.\n\n" +
                                "Install ProfMute again, or install uv from https://docs.astral.sh/uv/ and start ProfMute again.",
                                Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        if (ask && MessageBox.Show("Welcome to ProfMute.\n\n" +
                            "Before its first run, ProfMute has to download Python and the speech recognition and voice removal libraries " +
                            "into its own folder:\n\n" + dir + "\n\n" +
                            "That is about 4.7 GB and needs an internet connection. It takes several minutes and only happens once.\n\n" +
                            "Download now?",
                            Title + " - first-time setup", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK)
            return false;

        // Started by hand: a console window shows uv's progress, and stays open if something went
        // wrong so the reason can be read. Under the installer: no window and no waiting for a key;
        // what uv said goes to setup-log.txt instead.
        var setup = new ProcessStartInfo("cmd.exe", ask
            ? "/s /c \"title ProfMute setup & echo Downloading Python and the speech recognition and voice removal libraries, about 4.7 GB. " +
              "This window closes by itself when it is done. & echo. & \"" + uv + "\" sync --frozen || " +
              "(echo. & echo Setup did not finish. Check your internet connection, then start ProfMute again. & pause & exit /b 1)\""
            : "/s /c \"\"" + uv + "\" sync --frozen > setup-log.txt 2>&1\"");
        setup.WorkingDirectory = dir;
        setup.UseShellExecute = false;
        setup.CreateNoWindow = !ask;
        setup.EnvironmentVariables["UV_PYTHON_INSTALL_DIR"] = Path.Combine(dir, "python");   // keep Python in this folder too
        setup.EnvironmentVariables["UV_PYTHON_PREFERENCE"] = "only-managed";
        setup.EnvironmentVariables["UV_NO_CACHE"] = "1";                                      // no second copy left on the PC
        setup.EnvironmentVariables["UV_LINK_MODE"] = "copy";
        int code;
        try
        {
            using (Process p = Process.Start(setup))
            {
                p.WaitForExit();
                code = p.ExitCode;
            }
        }
        catch (Exception e)
        {
            if (ask)
                MessageBox.Show("Setup could not be started:\n\n" + e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        if (code == 0 && File.Exists(python))
        {
            File.WriteAllText(Marker(dir), "The first-time download finished. Delete the .venv folder to do it again.\r\n");
            return true;
        }
        if (ask)
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
