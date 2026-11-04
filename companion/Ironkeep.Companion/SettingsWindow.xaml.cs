using System;
using System.Windows;

namespace Ironkeep.Companion
{
    public partial class SettingsWindow : Window
    {
        readonly CompanionSession _session;
        readonly SettingsViewModel _model = new SettingsViewModel();
        bool _clearKey;
        bool _useLegacy;

        public SettingsWindow(CompanionSession session)
        {
            _session = session;
            InitializeComponent();
            WindowTheme.UseDarkCaption(this);
            _model.Load(session.Config, session.History());
            AddressBox.Text = _model.Address;
            SlugBox.Text = _model.Slug;
            FolderBox.Text = _model.WowFolder;
            StartupBox.IsChecked = _model.StartWithWindows;
            KeyNote.Text = _model.KeyNote;
            bool discord = session.Config.AuthMode == CompanionConfig.ModeDiscord;
            AddressBox.IsEnabled = !discord;
            SlugBox.IsEnabled = !discord;
            ShowError(session.Snapshot().LastError);
            HistoryList.ItemsSource = _model.History;
        }

        void ShowError(string error)
        {
            LastErrorText.Text = error == null || error.Length == 0 ? "None" : error;
        }

        void BrowseClick(object sender, RoutedEventArgs e)
        {
            var dialog = new Microsoft.Win32.OpenFolderDialog();
            dialog.Title = "Select the WoW Forever folder";
            if (dialog.ShowDialog(this) == true) FolderBox.Text = dialog.FolderName;
        }

        void ClearKeyClick(object sender, RoutedEventArgs e)
        {
            _clearKey = true;
            KeyBox.Password = "";
            KeyNote.Text = "The saved key will be removed when you save.";
        }

        void UseLegacyClick(object sender, RoutedEventArgs e)
        {
            _useLegacy = true;
            KeyNote.Text = "Uploads will use the legacy key after you save. The Discord session will be cleared.";
        }

        void RetryClick(object sender, RoutedEventArgs e)
        {
            IsEnabled = false;
            System.Threading.Tasks.Task.Run(delegate
            {
                try
                {
                    _session.RetryFailed();
                }
                finally
                {
                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        _model.Load(_session.Config, _session.History());
                        ShowError(_session.Snapshot().LastError);
                        HistoryList.ItemsSource = null;
                        HistoryList.ItemsSource = _model.History;
                        IsEnabled = true;
                    }));
                }
            });
        }

        void SaveClick(object sender, RoutedEventArgs e)
        {
            var config = new CompanionConfig();
            config.Address = AddressBox.Text.Trim();
            config.Slug = SlugBox.Text.Trim();
            config.WowFolder = FolderBox.Text.Trim();
            config.StartWithWindows = StartupBox.IsChecked == true;
            config.TrayExplained = _session.Config.TrayExplained;
            if (_clearKey) config.Token = "";
            else if (KeyBox.Password.Length > 0) config.Token = KeyBox.Password;
            else config.Token = _session.Config.Token ?? "";
            config.CopySession(_session.Config);
            if (_session.Config.AuthMode == CompanionConfig.ModeDiscord)
            {
                config.Address = _session.Config.Address;
                config.Slug = _session.Config.Slug;
            }
            if (_useLegacy)
            {
                if ((config.Token ?? "").Length == 0)
                {
                    MessageBox.Show(this, "Enter a legacy key first.", "Ironkeep Companion", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
                config.AuthMode = CompanionConfig.ModeLegacy;
                config.ClearDiscordSecrets();
            }
            try
            {
                _session.Save(config);
            }
            catch (System.InvalidOperationException ex)
            {
                MessageBox.Show(this, ex.Message, "Ironkeep Companion", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            DialogResult = true;
        }
    }
}
