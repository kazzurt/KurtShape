using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("KurtShape")]
[assembly: AssemblyDescription("KurtShape")]
[assembly: AssemblyProduct("KurtShape")]
[assembly: AssemblyCompany("KurtShape")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class KurtShapeLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        bool printOnly = Array.Exists(args, delegate(string value) {
            return value.Equals("-PrintOnly", StringComparison.OrdinalIgnoreCase)
                || value.StartsWith("-PrintOnly:", StringComparison.OrdinalIgnoreCase);
        });

        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(root, "launch-kurtshape.ps1");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            if (!File.Exists(script))
                throw new FileNotFoundException("The KurtShape launcher script is missing. Keep KurtShape.exe beside launch-kurtshape.ps1.", script);
            if (!File.Exists(powershell))
                throw new FileNotFoundException("Windows PowerShell could not be found.", powershell);

            StringBuilder arguments = new StringBuilder("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ");
            arguments.Append(QuoteArgument(script));
            foreach (string argument in args)
                arguments.Append(' ').Append(QuoteArgument(argument));

            ProcessStartInfo start = new ProcessStartInfo(powershell, arguments.ToString());
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.WorkingDirectory = root;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            StringBuilder errors = new StringBuilder();

            using (Process process = new Process())
            {
                process.StartInfo = start;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs output) {
                    if (output.Data != null) Console.Out.WriteLine(output.Data);
                };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs error) {
                    if (error.Data == null) return;
                    lock (errors) { errors.AppendLine(error.Data); }
                    Console.Error.WriteLine(error.Data);
                };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0 && !printOnly)
                {
                    string detail;
                    lock (errors) { detail = errors.ToString().Trim(); }
                    if (detail.Length == 0) detail = "The launcher exited with code " + process.ExitCode + ".";
                    MessageBox.Show(detail, "KurtShape could not start", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                return process.ExitCode;
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.Message);
            if (!printOnly)
                MessageBox.Show(exception.Message, "KurtShape could not start", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    // Escape one Windows native argument, including embedded quotes and trailing backslashes.
    private static string QuoteArgument(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { backslashes++; continue; }
            if (character == '"')
                result.Append('\\', backslashes * 2 + 1).Append('"');
            else
                result.Append('\\', backslashes).Append(character);
            backslashes = 0;
        }
        return result.Append('\\', backslashes * 2).Append('"').ToString();
    }
}
