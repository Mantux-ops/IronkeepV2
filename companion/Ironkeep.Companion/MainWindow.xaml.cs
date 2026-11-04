using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Threading;
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

        bool _fillingGuilds;

        public void Refresh()
        {
            if (_session.LoginBusy)
            {
                _model.ShowProgress(_session.LoginState);
                ApplyChrome();
                return;
            }
            _model.Apply(_session.Snapshot(), _session.Config, _session.SavedFileCount(), _session.Notice);
            FillGuilds();
            ApplyChrome();
        }

        void ApplyChrome()
        {
            ConnectButton.Visibility = _model.ShowConnect ? Visibility.Visible : Visibility.Collapsed;
            CancelButton.Visibility = _model.ShowCancel ? Visibility.Visible : Visibility.Collapsed;
            DisconnectButton.Visibility = _model.ShowDisconnect ? Visibility.Visible : Visibility.Collapsed;
            RetryButton.Visibility = _model.ShowRetry ? Visibility.Visible : Visibility.Collapsed;
            bool showGuilds = !_session.LoginBusy && _session.Config.AuthMode == CompanionConfig.ModeDiscord && GuildBox.Items.Count > 0;
            GuildBox.Visibility = showGuilds ? Visibility.Visible : Visibility.Collapsed;
            bool pair = DisconnectButton.Visibility == Visibility.Visible && RetryButton.Visibility == Visibility.Visible;
            System.Windows.Controls.Grid.SetColumn(DisconnectButton, 0);
            System.Windows.Controls.Grid.SetColumnSpan(DisconnectButton, pair ? 1 : 3);
            System.Windows.Controls.Grid.SetColumn(RetryButton, pair ? 2 : 0);
            System.Windows.Controls.Grid.SetColumnSpan(RetryButton, pair ? 1 : 3);
        }

        void FillGuilds()
        {
            _fillingGuilds = true;
            GuildBox.Items.Clear();
            var choices = _session.GuildChoices();
            int selected = -1;
            for (int i = 0; i < choices.Count; i++)
            {
                GuildBox.Items.Add(choices[i]);
                if (string.Equals(choices[i].Slug, _session.Config.Slug ?? "", StringComparison.OrdinalIgnoreCase)) selected = i;
            }
            if (selected >= 0) GuildBox.SelectedIndex = selected;
            _fillingGuilds = false;
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

        void ConnectClick(object sender, RoutedEventArgs e)
        {
            if (_session.LoginBusy) return;
            Task.Run(delegate
            {
                try
                {
                    _session.ConnectDiscord(CancellationToken.None);
                }
                finally
                {
                    Dispatcher.BeginInvoke(new Action(Refresh));
                }
            });
            Task.Delay(40).ContinueWith(delegate { Dispatcher.BeginInvoke(new Action(Refresh)); });
        }

        void CancelClick(object sender, RoutedEventArgs e)
        {
            _session.CancelConnect();
        }

        void DisconnectClick(object sender, RoutedEventArgs e)
        {
            IsEnabled = false;
            Task.Run(delegate
            {
                try
                {
                    _session.DisconnectDiscord();
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

        void RetryClick(object sender, RoutedEventArgs e)
        {
            if (_session.LoginBusy) return;
            IsEnabled = false;
            Task.Run(delegate
            {
                try
                {
                    _session.RetryAuthentication();
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

        void GuildChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
        {
            if (_fillingGuilds) return;
            var guild = GuildBox.SelectedItem as CompanionGuild;
            if (guild == null) return;
            if (string.Equals(guild.Slug, _session.Config.Slug ?? "", StringComparison.OrdinalIgnoreCase)) return;
            try
            {
                _session.SelectGuild(guild.Slug);
            }
            catch (InvalidOperationException ex)
            {
                MessageBox.Show(this, ex.Message, "Ironkeep Companion", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            Refresh();
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
