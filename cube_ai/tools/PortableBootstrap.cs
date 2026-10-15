using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class PortableBootstrap {
    [STAThread]
    private static void Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "运行环境", "python", "pythonw.exe");
            string entry = Path.Combine(root, "启动.pyw");
            if (!File.Exists(python) || !File.Exists(entry)) {
                MessageBox.Show("请先把压缩包完整解压，再从解压后的文件夹打开入口。请勿只取出单独的 EXE 文件。", "万智牌 Cube 助手");
                return;
            }
            string flags = Path.GetFileNameWithoutExtension(Application.ExecutablePath).StartsWith("关闭") ? " --stop" : "";
            foreach (string arg in args) {
                if (arg == "--no-browser" || arg == "--stop") flags += " " + arg;
            }
            ProcessStartInfo start = new ProcessStartInfo(python, "-X utf8 -B \"" + entry + "\"" + flags);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show("Cube 助手未能启动：\n" + error.Message, "万智牌 Cube 助手", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
