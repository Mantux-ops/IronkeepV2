using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Threading.Tasks;
using System.Windows;

namespace Ironkeep.Companion
{
    public partial class MainWindow : Window
    {
        readonly CompanionSession _session;
        readonly DashboardViewModel _model = new DashboardViewModel();

        public MainWindow(CompanionSession session)
        {
            _session = session;
            InitializeComponent();
            WindowTheme.UseDarkCaption(this);
            DataContext = _model;
            Refresh();
        }

        public bool AllowExit;

        public void Refresh()
        {
            _model.Apply(_session.Snapshot(), _session.Config, _session.SavedFileCount());
        }

        public void BringForward()
        {
            Show();
            WindowState = WindowState.Normal;
            Activate();
            Topmost = true;
            Topmost = false;
            Focus();
        }

        public static void OpenSite(CompanionSession session)
        {
            Process.Start(new ProcessStartInfo(CompanionSession.Website(session.Config)) { UseShellExecute = true });
        }

        protected override void OnClosing(CancelEventArgs e)
        {
            if (!AllowExit)
            {
                e.Cancel = true;
                if (!_session.Config.TrayExplained)
                {
                    MessageBox.Show(this,
                        "Ironkeep keeps running in the notification area and continues syncing. Choose Quit on the tray icon to exit.",
                        "Ironkeep Companion",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                    try
                    {
                        _session.MarkTrayExplained();
                    }
                    catch (System.InvalidOperationException ex)
                    {
                        MessageBox.Show(this, ex.Message, "Ironkeep Companion", MessageBoxButton.OK, MessageBoxImage.Warning);
                    }
                }
                Hide();
                return;
            }
            base.OnClosing(e);
        }

        void SyncClick(object sender, RoutedEventArgs e)
        {
            RunSync();
        }

        public void RunSync()
        {
            IsEnabled = false;
            Task.Run(delegate
            {
                try
                {
                    _session.SyncNow();
                }
                finally
                {
                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        Refresh();
                        IsEnabled = true;
                    }));
                }
            });
        }

        void WebClick(object sender, RoutedEventArgs e)
        {
            OpenSite(_session);
        }

        void SettingsClick(object sender, RoutedEventArgs e)
        {
            var settings = new SettingsWindow(_session) { Owner = this };
            if (settings.ShowDialog() == true) Refresh();
        }

        void HistoryClick(object sender, RoutedEventArgs e)
        {
            var settings = new SettingsWindow(_session) { Owner = this };
            if (settings.ShowDialog() == true) Refresh();
        }
    }
}
