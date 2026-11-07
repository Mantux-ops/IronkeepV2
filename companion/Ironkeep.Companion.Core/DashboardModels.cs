using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using Ironkeep;

namespace Ironkeep.Companion
{
    public sealed class DashboardViewModel : INotifyPropertyChanged
    {
        string _connection = "Idle";
        string _headline = "Idle";
        string _detail = "";
        string _level = "Idle";
        string _auth = "No legacy key";
        string _guild = "Not set";
        string _folder = "Not selected";
        string _folderStatus = "Choose the WoW Forever folder in Settings.";
        string _savedStatus = "SavedVariables have not been checked.";
        string _rosterStatus = "Roster file has not been checked.";
        string _syncState = "Idle";
        string _lastUpload = "None yet";
        string _pending = "0";
        string _retry = "0";
        string _failed = "0";
        string _lastError = "None";

        public event PropertyChangedEventHandler PropertyChanged;

        public string Version { get { return CompanionSession.Version; } }
        public string Connection { get { return _connection; } }
        public string Headline { get { return _headline; } }
        public string Detail { get { return _detail; } }
        public string Level { get { return _level; } }
        public string Auth { get { return _auth; } }
        public string Guild { get { return _guild; } }
        public string Folder { get { return _folder; } }
        public string FolderStatus { get { return _folderStatus; } }
        public string SavedStatus { get { return _savedStatus; } }
        public string RosterStatus { get { return _rosterStatus; } }
        public string SyncState { get { return _syncState; } }
        public string LastUpload { get { return _lastUpload; } }
        public string Pending { get { return _pending; } }
        public string Retry { get { return _retry; } }
        public string Failed { get { return _failed; } }
        public string LastError { get { return _lastError; } }
        public bool ShowConnect;
        public bool ShowCancel;
        public bool ShowDisconnect;
        public bool ShowRetry;
        string _cardDetail = "";
        public string CardDetail { get { return _cardDetail; } }

        public void ShowProgress(CompanionAuthState state)
        {
            string label = CompanionProtocol.Label(state);
            Set(ref _headline, label, "Headline");
            Set(ref _connection, label, "Connection");
            Set(ref _syncState, label, "SyncState");
            string detail = state == CompanionAuthState.AwaitingApproval
                ? "Approve the connection in your browser. This does not change your website login."
                : "Starting a local callback on this computer.";
            Set(ref _detail, detail, "Detail");
            Set(ref _level, "Warn", "Level");
            Set(ref _cardDetail, detail, "CardDetail");
            ShowConnect = false;
            ShowCancel = true;
            ShowDisconnect = false;
            ShowRetry = false;
        }

        public void Apply(SyncSnapshot snap, CompanionConfig config, int savedFiles)
        {
            Apply(snap, config, savedFiles, "");
        }

        public void Apply(SyncSnapshot snap, CompanionConfig config, int savedFiles, string notice)
        {
            if (snap == null) snap = new SyncSnapshot();
            if (config == null) config = new CompanionConfig();
            if (config.TokenUnreadable) Set(ref _auth, "Key could not be read", "Auth");
            else if ((config.Token ?? "").Length > 0) Set(ref _auth, "Legacy key saved", "Auth");
            else Set(ref _auth, "No legacy key", "Auth");
            Set(ref _guild, (config.Slug ?? "").Trim().Length == 0 ? "Not set" : config.Slug.Trim(), "Guild");
            string folder = (config.WowFolder ?? "").Trim();
            if (savedFiles < 0) savedFiles = 0;
            Set(ref _folder, folder.Length == 0 ? "Not selected" : folder, "Folder");
            if (folder.Length == 0) Set(ref _folderStatus, "No folder selected. This is not a detected install.", "FolderStatus");
            else if (!Directory.Exists(folder)) Set(ref _folderStatus, "That folder was not found.", "FolderStatus");
            else if (savedFiles > 0) Set(ref _folderStatus, "Forever SavedVariables layout found.", "FolderStatus");
            else Set(ref _folderStatus, "Folder found, but no Ironkeep.lua was found in a supported SavedVariables layout.", "FolderStatus");
            Set(ref _savedStatus, savedFiles == 0 ? "No Ironkeep.lua found." : savedFiles + " Ironkeep.lua file" + (savedFiles == 1 ? "" : "s") + " found.", "SavedStatus");
            Set(ref _rosterStatus, snap.RosterStatus == null || snap.RosterStatus.Length == 0 ? "No IronkeepRoster.lua found." : snap.RosterStatus, "RosterStatus");
            Set(ref _pending, snap.Pending.ToString(), "Pending");
            Set(ref _retry, snap.RetryScheduled.ToString(), "Retry");
            Set(ref _failed, snap.FailedPermanent.ToString(), "Failed");
            Set(ref _lastUpload, snap.LastConfirmedAt == null || snap.LastConfirmedAt.Length == 0 ? "None yet" : snap.LastConfirmedAt, "LastUpload");
            Set(ref _lastError, snap.LastError == null || snap.LastError.Length == 0 ? "None" : snap.LastError, "LastError");
            if (config.AuthMode == CompanionConfig.ModeDiscord)
            {
                ApplyDiscord(config, notice);
                return;
            }
            string state;
            string level;
            bool waitingForGuild = snap.WaitingForGuild || (config.Slug ?? "").Trim().Length == 0;
            if (snap.CorruptionDetected) { state = "Queue file was damaged"; level = "Bad"; }
            else if (waitingForGuild) { state = "Waiting for a guild"; level = "Warn"; }
            else if (snap.Pending + snap.Sending > 0) { state = "Upload queued"; level = "Warn"; }
            else if (snap.RetryScheduled > 0) { state = "Waiting to retry"; level = "Warn"; }
            else if (snap.FailedPermanent > 0) { state = "A report was rejected"; level = "Bad"; }
            else if (snap.LastConfirmedAt != null && snap.LastConfirmedAt.Length > 0) { state = "Up to date"; level = "Ok"; }
            else { state = "Idle"; level = "Idle"; }
            bool legacy = config.IsLegacy && !config.TokenUnreadable;
            if (config.TokenUnreadable) level = "Bad";
            else if (!legacy && level == "Ok") level = "Idle";
            Set(ref _syncState, state, "SyncState");
            string connection;
            if (config.TokenUnreadable) connection = "Key unreadable";
            else if (legacy) connection = "Legacy channel";
            else connection = "Not signed in";
            Set(ref _connection, connection, "Connection");
            string headline = legacy ? state : connection;
            string detail = legacy ? connection : state;
            if (!legacy && notice != null && notice.Length > 0)
            {
                headline = "Connection failed";
                detail = notice;
                level = "Bad";
            }
            Set(ref _headline, headline, "Headline");
            Set(ref _detail, detail, "Detail");
            Set(ref _level, level, "Level");
            ShowConnect = true;
            ShowCancel = false;
            ShowDisconnect = false;
            ShowRetry = notice != null && notice.Length > 0;
            string card = legacy
                ? "Uploads use the legacy guild key. Discord sign-in does not switch to it on failure."
                : (notice != null && notice.Length > 0 ? notice : "Connect with Discord. The website login stays in the browser.");
            if (config.TokenUnreadable) card = "The saved key could not be read. Enter it again in Settings.";
            Set(ref _cardDetail, card, "CardDetail");
        }

        void ApplyDiscord(CompanionConfig config, string notice)
        {
            string name = (config.GuildName ?? "").Length > 0 ? config.GuildName : (config.Slug ?? "");
            CompanionAuthState state = CompanionAuthState.NotConnected;
            string detail = "Connect with Discord. The website login stays in the browser.";
            string level = "Idle";
            if (config.SessionUnreadable)
            {
                state = CompanionAuthState.ConnectionFailed;
                detail = "The saved Discord session could not be read.";
                level = "Bad";
            }
            else if (notice != null && notice.Length > 0)
            {
                state = CompanionAuthState.ConnectionFailed;
                detail = notice;
                level = "Bad";
            }
            else if (config.SessionStatus == CompanionConfig.StatusExpired)
            {
                state = CompanionAuthState.SessionExpired;
                detail = "Sign in with Discord again. The legacy key is not used.";
                level = "Bad";
            }
            else if (config.SessionStatus == CompanionConfig.StatusDenied)
            {
                state = CompanionAuthState.PermissionDenied;
                detail = config.SessionDetail != null && config.SessionDetail.Length > 0 ? config.SessionDetail : "This account can no longer upload for that guild.";
                level = "Bad";
            }
            else if (config.SessionStatus == CompanionConfig.StatusFailed)
            {
                state = CompanionAuthState.ConnectionFailed;
                detail = config.SessionDetail != null && config.SessionDetail.Length > 0 ? config.SessionDetail : "The connection did not complete.";
                level = "Bad";
            }
            else if ((config.RefreshToken ?? "").Length == 0)
            {
                state = CompanionAuthState.NotConnected;
                detail = "Connect with Discord. The website login stays in the browser.";
                level = "Idle";
            }
            else if (config.SessionStatus == CompanionConfig.StatusChoose || (config.Slug ?? "").Trim().Length == 0)
            {
                state = CompanionAuthState.GuildSelectionRequired;
                detail = "Choose a guild returned by Ironkeep.";
                level = "Warn";
            }
            else
            {
                state = CompanionAuthState.Ready;
                detail = "Uploads go to " + name + " only.";
                level = "Ok";
            }
            string label = CompanionProtocol.Label(state);
            Set(ref _syncState, label, "SyncState");
            Set(ref _connection, "Discord", "Connection");
            Set(ref _headline, label, "Headline");
            Set(ref _detail, detail, "Detail");
            Set(ref _level, level, "Level");
            Set(ref _auth, "Discord session", "Auth");
            if (name.Length > 0) Set(ref _guild, name, "Guild");
            ShowConnect = state != CompanionAuthState.Ready;
            ShowCancel = false;
            ShowDisconnect = true;
            ShowRetry = state == CompanionAuthState.SessionExpired || state == CompanionAuthState.PermissionDenied || state == CompanionAuthState.ConnectionFailed || state == CompanionAuthState.GuildSelectionRequired;
            Set(ref _cardDetail, detail, "CardDetail");
        }

        void Set(ref string field, string value, string name)
        {
            if (field == value) return;
            field = value ?? "";
            PropertyChangedEventHandler handler = PropertyChanged;
            if (handler != null) handler(this, new PropertyChangedEventArgs(name));
        }
    }

    public sealed class HistoryRow
    {
        public string Id { get; set; }
        public string When { get; set; }
        public string State { get; set; }
        public string Detail { get; set; }
        public string Source { get; set; }
    }

    public sealed class SettingsViewModel
    {
        public string Address = "https://ironkeep.gg";
        public string Slug = "";
        public string WowFolder = "";
        public bool StartWithWindows;
        public bool HasKey;
        public string KeyNote = "No legacy key saved.";
        public List<HistoryRow> History = new List<HistoryRow>();

        public void Load(CompanionConfig config, IList<QueueItem> items)
        {
            if (config == null) config = new CompanionConfig();
            Address = config.Address ?? "https://ironkeep.gg";
            Slug = config.Slug ?? "";
            WowFolder = config.WowFolder ?? "";
            StartWithWindows = config.StartWithWindows;
            HasKey = (config.Token ?? "").Length > 0;
            if (config.TokenUnreadable) KeyNote = "The saved key could not be read. Enter it again.";
            else if (HasKey) KeyNote = "A legacy key is saved for this Windows user. It is not shown.";
            else KeyNote = "No legacy key saved.";
            History = new List<HistoryRow>();
            if (items == null) return;
            foreach (QueueItem item in items)
            {
                var row = new HistoryRow();
                row.Id = item.Id ?? "";
                row.When = item.UpdatedAt ?? "";
                row.State = Label(item.State);
                string detail = item.LastError ?? "";
                if (detail.Length == 0 && item.ConfirmedAt != null && item.ConfirmedAt.Length > 0) detail = "Confirmed " + item.ConfirmedAt;
                row.Detail = detail;
                row.Source = item.SourcePath == null || item.SourcePath.Length == 0 ? "" : Path.GetFileName(item.SourcePath);
                History.Add(row);
            }
        }

        static string Label(string state)
        {
            if (state == SyncState.Pending) return "Pending";
            if (state == SyncState.Sending) return "Sending";
            if (state == SyncState.Confirmed) return "Confirmed";
            if (state == SyncState.RetryScheduled) return "Retry scheduled";
            if (state == SyncState.FailedPermanent) return "Failed";
            return state ?? "";
        }
    }

    public sealed class TrayActions
    {
        readonly Action _open;
        readonly Action _sync;
        readonly Action _website;
        readonly Action _quit;

        public TrayActions(Action open, Action sync, Action website, Action quit)
        {
            _open = open;
            _sync = sync;
            _website = website;
            _quit = quit;
        }

        public void Open() { if (_open != null) _open(); }
        public void Sync() { if (_sync != null) _sync(); }
        public void Website() { if (_website != null) _website(); }
        public void Quit() { if (_quit != null) _quit(); }
    }
}
