using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        try
        {
            if (!File.Exists(python))
                throw new FileNotFoundException("Python-Umgebung fehlt. Bitte setup.ps1 ausführen.");
            var start = new ProcessStartInfo(python);
            start.Arguments = "-B \"" + Path.Combine(root, "main_app.py") + "\"";
            if (Array.IndexOf(args, "--show") >= 0) start.Arguments += " --show";
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            using (Process child = Process.Start(start)) { }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "TTS Vorleser – Startfehler",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
