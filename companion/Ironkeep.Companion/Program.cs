using System;
using System.IO;
using System.Windows;
using Ironkeep;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace Ironkeep.Companion
{
    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            try
            {
                File.WriteAllText(Path.Combine(Path.GetTempPath(), "ironkeep-wpf-start.txt"),
                    "args=" + (args == null ? "" : string.Join(" ", args)) + Environment.NewLine);
            }
            catch (Exception)
            {
            }
            if (args != null && args.Length > 0 && args[0] == "--send-check") return SendCheck(args);
            if (args != null && args.Length > 0 && args[0] == "--capture") return Capture(args);
            var app = new App();
            app.InitializeComponent();
            app.Startup += Start;
            app.Run();
            return 0;
        }

        static void Start(object sender, StartupEventArgs e)
        {
            var app = (App)sender;
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var instance = SingleInstance.Acquire("IronkeepCompanion");
            if (!instance.IsOwner)
            {
                instance.Signal();
                instance.Dispose();
                app.Shutdown();
                return;
            }
            var session = CompanionSession.ForCurrentUser();
            session.Start();
            var window = new MainWindow(session);
            NotifyIconHost host = null;
            var tray = TrayIcon.Create(window, session, delegate
            {
                window.AllowExit = true;
                if (host != null) host.Dispose();
                window.Close();
                session.Dispose();
                instance.Dispose();
                app.Shutdown();
            });
            host = new NotifyIconHost(tray);
            window.Show();
            var timer = new DispatcherTimer();
            timer.Interval = TimeSpan.FromMilliseconds(500);
            timer.Tick += delegate
            {
                if (instance.Consume()) window.BringForward();
                if (window.IsVisible) window.Refresh();
            };
            timer.Start();
        }

        static int SendCheck(string[] args)
        {
            if (args.Length < 5)
            {
                Console.Error.WriteLine("Usage: IronkeepCompanion --send-check <url> <slug> <token> <lua>");
                return 2;
            }
            string root = Path.Combine(Path.GetTempPath(), "ironkeep-send-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            string saved = Path.Combine(root, "wow", "WTF", "Account", "Send", "SavedVariables");
            Directory.CreateDirectory(saved);
            File.Copy(args[4], Path.Combine(saved, "Ironkeep.lua"), true);
            var config = new CompanionConfig();
            config.Address = args[1];
            config.Slug = args[2];
            config.Token = args[3];
            config.WowFolder = Path.Combine(root, "wow");
            var uploader = new LegacyUploader(delegate { return config; });
            var session = new CompanionSession(
                Path.Combine(root, "queue.sqlite"),
                Path.Combine(root, "settings.txt"),
                new PrefixProtector(),
                new MemoryStartup(),
                "",
                uploader);
            try
            {
                session.UseMemory(config);
                session.SyncNow();
                Console.WriteLine(uploader.LastResponse ?? "");
                return SiteClient.Accepted(uploader.LastResponse) ? 0 : 1;
            }
            finally
            {
                session.Dispose();
            }
        }

        static int Capture(string[] args)
        {
            if (args.Length < 2) return 2;
            string directory = args[1];
            Directory.CreateDirectory(directory);
            string root = Path.Combine(Path.GetTempPath(), "ironkeep-preview-" + Guid.NewGuid().ToString("N"));
            string saved = Path.Combine(root, "wow", "WTF", "Account", "Preview", "SavedVariables");
            Directory.CreateDirectory(saved);
            string sample = Path.Combine(AppContext.BaseDirectory, "sample-Ironkeep.lua");
            if (!File.Exists(sample)) sample = Path.Combine(Directory.GetCurrentDirectory(), "sample-Ironkeep.lua");
            if (!File.Exists(sample))
            {
                Console.Error.WriteLine("sample-Ironkeep.lua was not next to the application.");
                return 3;
            }
            File.Copy(sample, Path.Combine(saved, "Ironkeep.lua"), true);
            var memory = new CompanionConfig();
            memory.Address = "https://ironkeep.gg";
            memory.Slug = "preview";
            memory.WowFolder = Path.Combine(root, "wow");
            var session = new CompanionSession(
                Path.Combine(root, "queue.sqlite"),
                Path.Combine(root, "settings.txt"),
                new PrefixProtector(),
                new MemoryStartup(),
                "",
                new LegacyUploader(delegate { return memory; }));
            int code = 0;
            var app = new App();
            app.InitializeComponent();
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            app.Startup += delegate
            {
                app.Dispatcher.BeginInvoke(new Action(delegate
                {
                    try
                    {
                        session.UseMemory(memory);
                        session.Discover();
                        var dashboard = new MainWindow(session);
                        Save(dashboard, Path.Combine(directory, "dashboard.png"));
                        var settings = new SettingsWindow(session);
                        Save(settings, Path.Combine(directory, "settings.png"));
                        dashboard.AllowExit = true;
                        if (settings.IsVisible) settings.Close();
                        if (dashboard.IsVisible) dashboard.Close();
                    }
                    catch (Exception ex)
                    {
                        code = 1;
                        File.WriteAllText(Path.Combine(directory, "capture-error.txt"), ex.ToString());
                    }
                    finally
                    {
                        session.Dispose();
                        app.Shutdown(code);
                    }
                }));
            };
            int run = app.Run();
            return code != 0 ? code : run;
        }

        static void Save(Window window, string path)
        {
            try
            {
                window.Show();
                window.UpdateLayout();
            }
            catch (Exception)
            {
            }
            Visual visual = window;
            int width = (int)Math.Ceiling(window.ActualWidth);
            int height = (int)Math.Ceiling(window.ActualHeight);
            if (width < 50 || height < 50)
            {
                var root = window.Content as FrameworkElement;
                if (root == null) throw new InvalidOperationException("The window has no content.");
                double layoutWidth = window.Width > 50 ? window.Width : 460;
                double layoutHeight = window.Height > 50 ? window.Height : 640;
                root.Measure(new Size(layoutWidth, layoutHeight));
                root.Arrange(new Rect(0, 0, layoutWidth, layoutHeight));
                root.UpdateLayout();
                width = (int)Math.Ceiling(root.RenderSize.Width);
                height = (int)Math.Ceiling(root.RenderSize.Height);
                if (width < 50) width = (int)layoutWidth;
                if (height < 50) height = (int)layoutHeight;
                visual = root;
            }
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(visual);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var stream = File.Create(path)) encoder.Save(stream);
        }
    }

    sealed class NotifyIconHost : IDisposable
    {
        readonly System.Windows.Forms.NotifyIcon _icon;

        public NotifyIconHost(System.Windows.Forms.NotifyIcon icon)
        {
            _icon = icon;
        }

        public void Dispose()
        {
            _icon.Visible = false;
            _icon.Dispose();
        }
    }
}
