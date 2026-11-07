using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace Ironkeep
{
    static class App
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainWindow());
        }
    }

    sealed class MainWindow : Form
    {
        static readonly Color Bg = Color.FromArgb(12, 14, 18);
        static readonly Color Panel = Color.FromArgb(19, 22, 28);
        static readonly Color Panel2 = Color.FromArgb(24, 28, 35);
        static readonly Color Panel3 = Color.FromArgb(30, 35, 43);
        static readonly Color Border = Color.FromArgb(49, 56, 67);
        static readonly Color TextMain = Color.FromArgb(231, 233, 236);
        static readonly Color Muted = Color.FromArgb(141, 149, 161);
        static readonly Color Accent = Color.FromArgb(45, 212, 191);
        static readonly Color AccentStrong = Color.FromArgb(94, 234, 212);
        static readonly Color Warning = Color.FromArgb(245, 165, 36);
        static readonly Color Here = Color.FromArgb(63, 210, 143);

        readonly Panel brand = new Panel();
        readonly Panel pathRow = new Panel();
        readonly Panel meta = new Panel();
        readonly Panel siteRow = new Panel();
        readonly Panel bottom = new Panel();
        readonly PictureBox logo = new PictureBox();
        readonly Label titleLabel = new Label();
        readonly Label subtitleLabel = new Label();
        readonly TextBox pathBox = new TextBox();
        readonly Button browseButton;
        readonly Button refreshButton;
        readonly Label placeLabel = new Label();
        readonly Label detailLabel = new Label();
        readonly Label countLabel = new Label();
        readonly DataGridView grid = new DataGridView();
        readonly TextBox reportBox = new TextBox();
        readonly TextBox addressBox = new TextBox();
        readonly TextBox slugBox = new TextBox();
        readonly TextBox tokenBox = new TextBox();
        readonly Label addressLabel = new Label();
        readonly Label slugLabel = new Label();
        readonly Label tokenLabel = new Label();
        readonly Label siteNote = new Label();
        readonly Button copyButton;
        readonly Button sampleButton;
        readonly Button sendButton;
        readonly Label hintLabel = new Label();
        readonly Label statusLabel = new Label();
        MemoryStream logoStream;
        readonly SiteStore sites = SiteStore.ForUser();
        readonly SendLedger ledger = SendLedger.ForUser();
        readonly SettleWatch settle = new SettleWatch();
        readonly List<string> retryQueue = new List<string>();
        Timer settleTimer;
        Timer retryTimer;
        FileSystemWatcher watcher;
        string reportText = "";
        bool sampleShowing;
        string loadedFile = "";
        string settlePath = "";
        int cutoffTries;
        int retryAttempt;

        public MainWindow()
        {
            Text = "Ironkeep Companion";
            Font = UiFont(10f, FontStyle.Regular);
            BackColor = Bg;
            ForeColor = TextMain;
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(760, 620);
            ClientSize = new Size(880, 680);
            DoubleBuffered = true;
            KeyPreview = true;

            browseButton = MakeButton("Kies map", false);
            refreshButton = MakeButton("Vernieuwen", true);
            copyButton = MakeButton("Kopieer lijst", false);
            sampleButton = MakeButton("Voorbeeld", false);
            sendButton = MakeButton("Stuur naar de site", true);
            copyButton.Enabled = false;

            StylePanel(brand, 72, DockStyle.Top);
            StylePanel(pathRow, 48, DockStyle.Top);
            StylePanel(meta, 58, DockStyle.Top);
            StylePanel(siteRow, 96, DockStyle.Top);
            StylePanel(bottom, 78, DockStyle.Bottom);

            logo.BackColor = Bg;
            logo.SizeMode = PictureBoxSizeMode.Zoom;
            StyleLabel(titleLabel, "Ironkeep Companion", TextMain, 15f, FontStyle.Bold);
            StyleLabel(subtitleLabel, "De groepslijst die de addon bewaart bij uitloggen of /reload.", Muted, 9.5f, FontStyle.Regular);

            pathBox.BorderStyle = BorderStyle.FixedSingle;
            pathBox.BackColor = Panel3;
            pathBox.ForeColor = TextMain;
            pathBox.Font = UiFont(10f, FontStyle.Regular);
            pathBox.KeyDown += PathKeyDown;
            StyleBox(addressBox);
            StyleBox(slugBox);
            StyleBox(tokenBox);
            tokenBox.UseSystemPasswordChar = true;
            StyleLabel(addressLabel, "Adres", Muted, 9f, FontStyle.Regular);
            StyleLabel(slugLabel, "Gilde", Muted, 9f, FontStyle.Regular);
            StyleLabel(tokenLabel, "Sleutel", Muted, 9f, FontStyle.Regular);
            StyleLabel(siteNote, "Vul jullie Forever-gilde zelf in. Dutch Chaos hoort hier niet.", Muted, 9f, FontStyle.Regular);
            LoadSite();
            addressBox.Leave += delegate { SaveSite(); };
            slugBox.Leave += delegate { SaveSite(); };
            tokenBox.Leave += delegate { SaveSite(); };

            StyleLabel(placeLabel, "Geen lijst", TextMain, 16f, FontStyle.Bold);
            StyleLabel(detailLabel, "", Muted, 9.5f, FontStyle.Regular);
            StyleLabel(countLabel, "", TextMain, 11f, FontStyle.Regular);
            countLabel.TextAlign = ContentAlignment.MiddleRight;

            StyleGrid();
            reportBox.Multiline = true;
            reportBox.ReadOnly = true;
            reportBox.BorderStyle = BorderStyle.None;
            reportBox.BackColor = Panel;
            reportBox.ForeColor = TextMain;
            reportBox.ScrollBars = ScrollBars.Both;
            reportBox.WordWrap = false;
            reportBox.Visible = false;
            reportBox.Font = MonoFont(10f);
            reportBox.Dock = DockStyle.None;

            StyleLabel(hintLabel, "Plak de sleutel van de raids-pagina. Het voorbeeld wordt niet verstuurd.", Muted, 9.5f, FontStyle.Regular);
            StyleLabel(statusLabel, "", Muted, 9f, FontStyle.Regular);

            browseButton.Click += BrowseClick;
            refreshButton.Click += RefreshClick;
            copyButton.Click += CopyClick;
            sampleButton.Click += SampleClick;
            sendButton.Click += SendClick;

            brand.Controls.Add(logo);
            brand.Controls.Add(titleLabel);
            brand.Controls.Add(subtitleLabel);
            pathRow.Controls.Add(pathBox);
            pathRow.Controls.Add(browseButton);
            pathRow.Controls.Add(refreshButton);
            meta.Controls.Add(placeLabel);
            meta.Controls.Add(detailLabel);
            meta.Controls.Add(countLabel);
            siteRow.Controls.Add(addressLabel);
            siteRow.Controls.Add(slugLabel);
            siteRow.Controls.Add(tokenLabel);
            siteRow.Controls.Add(addressBox);
            siteRow.Controls.Add(slugBox);
            siteRow.Controls.Add(tokenBox);
            siteRow.Controls.Add(sendButton);
            siteRow.Controls.Add(siteNote);
            bottom.Controls.Add(copyButton);
            bottom.Controls.Add(sampleButton);
            bottom.Controls.Add(hintLabel);
            bottom.Controls.Add(statusLabel);

            var body = new Panel();
            body.Dock = DockStyle.Fill;
            body.BackColor = Bg;
            body.Padding = new Padding(20, 0, 20, 8);
            var frame = new Panel();
            frame.Dock = DockStyle.Fill;
            frame.BackColor = Border;
            frame.Padding = new Padding(1);
            grid.Dock = DockStyle.Fill;
            frame.Controls.Add(reportBox);
            frame.Controls.Add(grid);
            body.Controls.Add(frame);

            Controls.Add(body);
            Controls.Add(bottom);
            Controls.Add(siteRow);
            Controls.Add(meta);
            Controls.Add(pathRow);
            Controls.Add(brand);

            brand.Resize += delegate { LayoutChrome(); };
            pathRow.Resize += delegate { LayoutChrome(); };
            meta.Resize += delegate { LayoutChrome(); };
            siteRow.Resize += delegate { LayoutChrome(); };
            bottom.Resize += delegate { LayoutChrome(); };
            LoadLogo();
            LayoutChrome();
            settleTimer = new Timer();
            settleTimer.Interval = 400;
            settleTimer.Tick += SettleTick;
            retryTimer = new Timer();
            retryTimer.Tick += RetryTick;
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            try
            {
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch (Exception)
            {
            }
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            LoadInitial();
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.F5)
            {
                RefreshFromPath();
                e.Handled = true;
            }
            base.OnKeyDown(e);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            if (watcher != null) watcher.Dispose();
            if (settleTimer != null) settleTimer.Dispose();
            if (retryTimer != null) retryTimer.Dispose();
            if (logoStream != null) logoStream.Dispose();
            base.OnFormClosed(e);
        }

        void LayoutChrome()
        {
            if (pathBox == null || refreshButton == null || browseButton == null) return;
            int pathHeight = pathRow.ClientSize.Height - 8;
            if (pathHeight < 24) pathHeight = 24;
            refreshButton.SetBounds(pathRow.ClientSize.Width - 20 - 124, 4, 124, pathHeight);
            browseButton.SetBounds(refreshButton.Left - 8 - 112, 4, 112, pathHeight);
            pathBox.SetBounds(20, 8, Math.Max(40, browseButton.Left - 28), pathHeight - 8);

            placeLabel.SetBounds(20, 4, Math.Max(40, meta.ClientSize.Width - 200), 26);
            detailLabel.SetBounds(20, 30, Math.Max(40, meta.ClientSize.Width - 200), 20);
            countLabel.SetBounds(meta.ClientSize.Width - 180, 8, 160, 36);

            int sendWidth = 168;
            sendButton.SetBounds(siteRow.ClientSize.Width - 20 - sendWidth, 26, sendWidth, 32);
            int fields = Math.Max(80, sendButton.Left - 28);
            int addressWidth = Math.Max(180, (fields * 46) / 100);
            int slugWidth = Math.Max(110, (fields * 24) / 100);
            int tokenWidth = Math.Max(80, fields - addressWidth - slugWidth - 16);
            addressBox.SetBounds(20, 26, addressWidth, 28);
            slugBox.SetBounds(addressBox.Right + 8, 26, slugWidth, 28);
            tokenBox.SetBounds(slugBox.Right + 8, 26, tokenWidth, 28);
            addressLabel.SetBounds(20, 4, addressWidth, 20);
            slugLabel.SetBounds(slugBox.Left, 4, slugWidth, 20);
            tokenLabel.SetBounds(tokenBox.Left, 4, tokenWidth, 20);
            siteNote.SetBounds(20, 62, Math.Max(40, siteRow.ClientSize.Width - 40), 24);

            copyButton.SetBounds(20, 8, 156, 34);
            sampleButton.SetBounds(184, 8, 120, 34);
            hintLabel.SetBounds(316, 8, Math.Max(0, bottom.ClientSize.Width - 336), 34);
            statusLabel.SetBounds(20, 48, Math.Max(0, bottom.ClientSize.Width - 40), 20);

            logo.SetBounds(20, 15, 42, 42);
            titleLabel.SetBounds(74, 14, Math.Max(40, brand.ClientSize.Width - 94), 24);
            subtitleLabel.SetBounds(74, 38, Math.Max(40, brand.ClientSize.Width - 94), 20);
        }

        void LoadInitial()
        {
            string saved = ReadSetting();
            if (saved.Length > 0)
            {
                Watch(saved);
                if (TryFolder(saved)) return;
            }
            foreach (string folder in Saved.DefaultWowFolders())
            {
                if (TryFolder(folder)) return;
            }
            ClearGroup();
            SetStatus("Nog geen meting. Log uit of typ /reload, en klik daarna op Vernieuwen.", Warning);
        }

        void RefreshFromPath()
        {
            string path = pathBox.Text.Trim();
            if (path.Length == 0)
            {
                LoadInitial();
                return;
            }
            if (!TryFolder(path))
            {
                ClearGroup();
                SetStatus(Dutch("No Ironkeep.lua under " + path), Warning);
            }
        }

        bool TryFolder(string folder)
        {
            Watch(folder);
            List<string> files = Saved.AllSaved(folder);
            if (files.Count == 0)
            {
                try
                {
                    Saved.FindSaved(folder);
                }
                catch (SavedException ex)
                {
                    if (ex.Message.StartsWith("No Ironkeep.lua")) return false;
                    ClearGroup();
                    SetStatus(Dutch(ex.Message), Warning);
                    return true;
                }
                return false;
            }
            string show = Saved.Newest(files);
            bool offline = false;
            foreach (string file in files)
            {
                if (file == show) continue;
                if (Publish(file, false, false) == SendOutcome.Offline) offline = true;
            }
            if (Publish(show, false, true) == SendOutcome.Offline) offline = true;
            if (offline) NoteSend(SendOutcome.Offline);
            return true;
        }

        void NoteSend(SendOutcome outcome)
        {
            if (outcome != SendOutcome.Offline) return;
            int seconds = ScheduleBackoff();
            if (seconds == 0)
                SetStatus("De site is niet bereikbaar. Klik op Vernieuwen om het opnieuw te proberen.", Warning);
            else
                SetStatus("De site is niet bereikbaar. Nieuwe poging over " + seconds.ToString() + " seconden.", Warning);
        }

        SendOutcome Publish(string file, bool manual, bool show)
        {
            Dictionary<object, object> db;
            try
            {
                db = Saved.LoadPath(file);
            }
            catch (SavedException ex)
            {
                if (show)
                {
                    ClearGroup();
                    SetStatus(Dutch(ex.Message), Warning);
                }
                if (ex.Message == "This saved file is cut off.") NoteCutoff(file);
                return SendOutcome.Rejected;
            }
            GroupList group = Saved.Describe(db);
            if (show)
            {
                sampleShowing = false;
                loadedFile = file;
                string root = WowRoot(file);
                pathBox.Text = root.Length > 0 ? root : Path.GetDirectoryName(file);
                Remember(pathBox.Text);
                string when = File.GetLastWriteTime(file).ToString("yyyy-MM-dd HH:mm");
                ShowGroup(group, AccountOf(file), "Gelezen uit " + file + "    " + when, Muted);
            }
            return SendReport(group.Text, file, manual, show);
        }

        void ShowGroup(GroupList group, string account, string status, Color statusColor)
        {
            reportText = group.Text ?? "";
            copyButton.Enabled = reportText.Trim().Length > 0;
            if (group.Previous)
            {
                grid.Visible = false;
                grid.Dock = DockStyle.None;
                reportBox.Dock = DockStyle.Fill;
                reportBox.Visible = true;
                reportBox.Text = group.Text;
                string place = After(group.Text, "Place: ");
                string started = After(group.Text, "Started: ");
                placeLabel.Text = place.Length == 0 ? "Vorige lijst" : place;
                detailLabel.Text = started.Length == 0 ? "Vorige lijst. Er is nu geen open sessie." : "gestart " + started + "    vorige lijst";
                countLabel.Text = "Vorige lijst";
            }
            else
            {
                reportBox.Visible = false;
                reportBox.Dock = DockStyle.None;
                grid.Dock = DockStyle.Fill;
                grid.Visible = true;
                grid.Rows.Clear();
                int here = 0;
                int away = 0;
                foreach (PersonLine person in group.People)
                {
                    if (person.Here) here++;
                    else away++;
                    int index = grid.Rows.Add(person.Name, person.ClassName, person.Role, person.Time, person.Here ? "hier" : "weg");
                    DataGridViewRow row = grid.Rows[index];
                    row.Cells[0].Style.ForeColor = ClassColor(person.ClassFile, person.ClassName);
                    row.Cells[4].Style.ForeColor = person.Here ? Here : Muted;
                }
                placeLabel.Text = group.Place.Length == 0 ? "Geen lijst" : group.Place;
                string detail = group.Started.Length == 0 ? "" : "gestart " + group.Started;
                if (account.Length > 0)
                    detail = detail.Length == 0 ? "account " + account : detail + "    account " + account;
                detailLabel.Text = detail;
                countLabel.Text = here.ToString() + " hier, " + away.ToString() + " weg";
            }
            SetStatus(status, statusColor);
        }

        void ClearGroup()
        {
            reportText = "";
            sampleShowing = false;
            loadedFile = "";
            copyButton.Enabled = false;
            grid.Rows.Clear();
            reportBox.Visible = false;
            reportBox.Dock = DockStyle.None;
            grid.Dock = DockStyle.Fill;
            grid.Visible = true;
            reportBox.Text = "";
            placeLabel.Text = "Geen lijst";
            detailLabel.Text = "";
            countLabel.Text = "";
        }

        void BrowseClick(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "Kies de map van WoW: Forever";
                dialog.ShowNewFolderButton = false;
                if (Directory.Exists(pathBox.Text)) dialog.SelectedPath = pathBox.Text;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                pathBox.Text = dialog.SelectedPath;
            }
            RefreshFromPath();
        }

        void RefreshClick(object sender, EventArgs e)
        {
            RefreshFromPath();
        }

        void SampleClick(object sender, EventArgs e)
        {
            try
            {
                sampleShowing = true;
                GroupList group = Saved.Describe(Saved.Load(Saved.EmbeddedSample()));
                ShowGroup(group, "", "Ingebouwd voorbeeld. Dit is niet je eigen meting.", Accent);
            }
            catch (SavedException ex)
            {
                SetStatus(Dutch(ex.Message), Warning);
            }
        }

        void CopyClick(object sender, EventArgs e)
        {
            if (reportText.Length == 0) return;
            try
            {
                Clipboard.SetText(reportText);
                SetStatus("De lijst staat op het klembord.", Accent);
            }
            catch (ExternalException)
            {
                SetStatus("Kopiëren lukte niet.", Warning);
            }
        }

        void PathKeyDown(object sender, KeyEventArgs e)
        {
            if (e.KeyCode != Keys.Enter) return;
            e.SuppressKeyPress = true;
            RefreshFromPath();
        }

        void SendClick(object sender, EventArgs e)
        {
            if (sampleShowing)
            {
                SetStatus("Het voorbeeld wordt niet verstuurd.", Warning);
                return;
            }
            NoteSend(SendReport(reportText, loadedFile, true, true));
        }

        SendOutcome SendReport(string text, string path, bool manual, bool show)
        {
            SaveSite();
            if (text == null) text = "";
            if (text.Trim().Length == 0)
            {
                if (manual) SetStatus("Er is nog geen lijst om te versturen.", Warning);
                return SendOutcome.Rejected;
            }
            string hash = ReportHash.Of(text);
            if (!manual && path != null && path.Length > 0 && ledger.Has(path, hash))
                return SendOutcome.Skipped;
            string token = tokenBox.Text.Trim();
            if (token.Length == 0 || token.IndexOf('\n') >= 0 || token.IndexOf('\r') >= 0)
            {
                if (manual || show) SetStatus("Plak de sleutel van de raids-pagina.", Warning);
                return SendOutcome.Auth;
            }
            string problem;
            Uri url = SiteClient.Target(addressBox.Text, slugBox.Text, out problem);
            if (url == null)
            {
                if (manual || show) SetStatus(problem, Warning);
                return SendOutcome.Auth;
            }
            try
            {
                int status;
                string response = SiteClient.Post(url, token, text, out status);
                if (status >= 200 && status < 300 && SiteClient.Accepted(response))
                {
                    if (path != null && path.Length > 0) ledger.Remember(path, hash);
                    retryQueue.Remove(path);
                    if (show || manual)
                    {
                        if (SiteClient.Duplicate(response)) SetStatus("Die lijst stond al op de site.", Accent);
                        else SetStatus("Verstuurd naar de site.", Accent);
                    }
                    return SendOutcome.Sent;
                }
                if (show || manual) SetStatus(SendStatus(status), Warning);
                if (SiteClient.Retryable(status))
                {
                    RememberRetry(path);
                    return SendOutcome.Offline;
                }
                return status == 401 ? SendOutcome.Auth : SendOutcome.Rejected;
            }
            catch (WebException)
            {
                RememberRetry(path);
                if (show || manual) SetStatus("De site is niet bereikbaar.", Warning);
                return SendOutcome.Offline;
            }
        }

        static string SendStatus(int status)
        {
            if (status == 401) return "De sleutel klopt niet. Kopieer hem opnieuw van de raids-pagina.";
            if (status == 404) return "Die gilde staat niet op dit adres.";
            if (status == 413) return "De lijst is te groot.";
            return "De site nam de lijst niet aan.";
        }

        void LoadSite()
        {
            addressBox.Text = "https://ironkeep.gg";
            slugBox.Text = "";
            tokenBox.Text = "";
            SiteSettings site = sites.Load();
            if (site.Address.Length > 0) addressBox.Text = site.Address;
            if (site.Slug.Length > 0) slugBox.Text = site.Slug;
            tokenBox.Text = site.Token;
            if (site.Unreadable)
                SetStatus("De sleutel op deze pc kon niet gelezen worden. Plak hem opnieuw.", Warning);
        }

        void SaveSite()
        {
            sites.Save(addressBox.Text, slugBox.Text, tokenBox.Text);
        }

        void Watch(string start)
        {
            if (watcher != null)
            {
                watcher.EnableRaisingEvents = false;
                watcher.Dispose();
                watcher = null;
            }
            if (start == null) return;
            string dir = start.Trim();
            if (dir.Length == 0) return;
            if (File.Exists(dir)) dir = Path.GetDirectoryName(dir);
            if (dir == null || !Directory.Exists(dir)) return;
            watcher = new FileSystemWatcher(dir);
            watcher.Filter = "Ironkeep.lua";
            watcher.IncludeSubdirectories = true;
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
            watcher.Changed += OnSaved;
            watcher.Created += OnSaved;
            watcher.Renamed += OnSaved;
            watcher.EnableRaisingEvents = true;
        }

        void OnSaved(object sender, FileSystemEventArgs e)
        {
            string path = e.FullPath;
            if (path == null || path.IndexOf("Ironkeep.lua", StringComparison.OrdinalIgnoreCase) < 0) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate { Arm(path); });
            }
            catch (InvalidOperationException)
            {
            }
        }

        void Arm(string path)
        {
            settlePath = path;
            cutoffTries = 0;
            settle.Reset();
            settleTimer.Stop();
            settleTimer.Start();
        }

        void SettleTick(object sender, EventArgs e)
        {
            settleTimer.Stop();
            if (settlePath.Length == 0 || !File.Exists(settlePath)) return;
            long length = new FileInfo(settlePath).Length;
            if (!settle.Due(length))
            {
                settleTimer.Start();
                return;
            }
            NoteSend(Publish(settlePath, false, true));
        }

        void NoteCutoff(string file)
        {
            if (file != settlePath) return;
            cutoffTries++;
            if (cutoffTries >= 4) return;
            settle.Reset();
            settleTimer.Start();
        }

        void RememberRetry(string path)
        {
            if (path == null || path.Length == 0) return;
            if (!retryQueue.Contains(path)) retryQueue.Add(path);
        }

        int ScheduleBackoff()
        {
            retryAttempt++;
            int seconds = SendRetry.Seconds(retryAttempt);
            if (seconds == 0)
            {
                retryQueue.Clear();
                retryAttempt = 0;
                return 0;
            }
            retryTimer.Stop();
            retryTimer.Interval = seconds * 1000;
            retryTimer.Start();
            return seconds;
        }

        void RetryTick(object sender, EventArgs e)
        {
            retryTimer.Stop();
            if (retryQueue.Count == 0)
            {
                retryAttempt = 0;
                return;
            }
            var pending = new List<string>(retryQueue);
            retryQueue.Clear();
            SendOutcome worst = SendOutcome.Sent;
            for (int i = 0; i < pending.Count; i++)
            {
                SendOutcome outcome = Publish(pending[i], false, i == pending.Count - 1);
                if (outcome == SendOutcome.Offline) worst = SendOutcome.Offline;
            }
            if (worst == SendOutcome.Offline) NoteSend(worst);
            else retryAttempt = 0;
        }

        static void StyleBox(TextBox box)
        {
            box.BorderStyle = BorderStyle.FixedSingle;
            box.BackColor = Panel3;
            box.ForeColor = TextMain;
            box.Font = UiFont(10f, FontStyle.Regular);
        }

        void SetStatus(string text, Color color)
        {
            statusLabel.Text = text;
            statusLabel.ForeColor = color;
        }

        void LoadLogo()
        {
            Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("logo.png");
            if (stream == null) return;
            logoStream = new MemoryStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                logoStream.Write(buffer, 0, read);
            stream.Dispose();
            logoStream.Position = 0;
            logo.Image = Image.FromStream(logoStream);
        }

        static void StylePanel(Panel panel, int height, DockStyle dock)
        {
            panel.Dock = dock;
            panel.Height = height;
            panel.BackColor = Bg;
        }

        static void StyleLabel(Label label, string text, Color color, float size, FontStyle style)
        {
            label.Text = text;
            label.ForeColor = color;
            label.BackColor = Color.Transparent;
            label.Font = UiFont(size, style);
            label.AutoSize = false;
            label.AutoEllipsis = true;
            label.TextAlign = ContentAlignment.MiddleLeft;
        }

        void StyleGrid()
        {
            grid.BackgroundColor = Panel;
            grid.BorderStyle = BorderStyle.None;
            grid.CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal;
            grid.GridColor = Border;
            grid.EnableHeadersVisualStyles = false;
            grid.ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.None;
            grid.RowHeadersVisible = false;
            grid.AllowUserToAddRows = false;
            grid.AllowUserToDeleteRows = false;
            grid.AllowUserToResizeRows = false;
            grid.ReadOnly = true;
            grid.MultiSelect = false;
            grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
            grid.RowTemplate.Height = 34;
            grid.ColumnHeadersHeight = 32;
            grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
            grid.AutoGenerateColumns = false;
            grid.Font = UiFont(10f, FontStyle.Regular);

            grid.DefaultCellStyle.BackColor = Panel;
            grid.DefaultCellStyle.ForeColor = TextMain;
            grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(28, 62, 58);
            grid.DefaultCellStyle.SelectionForeColor = TextMain;
            grid.DefaultCellStyle.Padding = new Padding(8, 0, 8, 0);
            grid.AlternatingRowsDefaultCellStyle.BackColor = Panel2;
            grid.AlternatingRowsDefaultCellStyle.ForeColor = TextMain;
            grid.AlternatingRowsDefaultCellStyle.SelectionBackColor = Color.FromArgb(28, 62, 58);
            grid.AlternatingRowsDefaultCellStyle.SelectionForeColor = TextMain;
            grid.ColumnHeadersDefaultCellStyle.BackColor = Panel2;
            grid.ColumnHeadersDefaultCellStyle.ForeColor = Muted;
            grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Panel2;
            grid.ColumnHeadersDefaultCellStyle.SelectionForeColor = Muted;
            grid.ColumnHeadersDefaultCellStyle.Font = UiFont(9f, FontStyle.Regular);
            grid.ColumnHeadersDefaultCellStyle.Padding = new Padding(8, 0, 8, 0);

            AddColumn("Naam", 180, true);
            AddColumn("Klasse", 120, false);
            AddColumn("Rol", 100, false);
            AddColumn("Tijd", 80, false);
            AddColumn("Status", 80, false);
        }

        void AddColumn(string header, int width, bool fill)
        {
            var column = new DataGridViewTextBoxColumn();
            column.Name = header;
            column.HeaderText = header;
            column.SortMode = DataGridViewColumnSortMode.NotSortable;
            if (fill) column.AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill;
            else column.Width = width;
            grid.Columns.Add(column);
        }

        Button MakeButton(string text, bool primary)
        {
            var button = new Button();
            button.Text = text;
            button.FlatStyle = FlatStyle.Flat;
            button.UseVisualStyleBackColor = false;
            button.FlatAppearance.BorderSize = primary ? 0 : 1;
            button.FlatAppearance.BorderColor = Border;
            Color back = primary ? Accent : Panel3;
            button.BackColor = back;
            button.ForeColor = primary ? Bg : TextMain;
            button.Font = UiFont(9.5f, FontStyle.Bold);
            button.Cursor = Cursors.Hand;
            button.MouseEnter += delegate { button.BackColor = primary ? AccentStrong : Border; };
            button.MouseLeave += delegate { button.BackColor = back; };
            return button;
        }

        static string SettingsFile()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Ironkeep", "companion-folder.txt");
        }

        static string ReadSetting()
        {
            try
            {
                string file = SettingsFile();
                if (!File.Exists(file)) return "";
                return File.ReadAllText(file).Trim();
            }
            catch (IOException)
            {
                return "";
            }
            catch (UnauthorizedAccessException)
            {
                return "";
            }
        }

        static void Remember(string folder)
        {
            try
            {
                string file = SettingsFile();
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                File.WriteAllText(file, folder);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        static string WowRoot(string file)
        {
            string marker = Path.DirectorySeparatorChar + "WTF" + Path.DirectorySeparatorChar + "Account" + Path.DirectorySeparatorChar;
            int at = file.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
            if (at > 0) return file.Substring(0, at);
            return "";
        }

        static string AccountOf(string file)
        {
            string marker = Path.DirectorySeparatorChar + "Account" + Path.DirectorySeparatorChar;
            int at = file.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
            if (at < 0) return "";
            string rest = file.Substring(at + marker.Length);
            int slash = rest.IndexOf(Path.DirectorySeparatorChar);
            if (slash <= 0) return "";
            return rest.Substring(0, slash);
        }

        static string After(string text, string prefix)
        {
            if (text == null) return "";
            string[] lines = text.Replace("\r", "").Split('\n');
            for (int i = 0; i < lines.Length; i++)
            {
                if (lines[i].StartsWith(prefix)) return lines[i].Substring(prefix.Length).Trim();
            }
            return "";
        }

        static string Dutch(string message)
        {
            if (message == null) return "Dit bestand kon niet gelezen worden.";
            if (message.StartsWith("Could not open ")) return "Dit bestand kon niet geopend worden.";
            if (message.StartsWith("No Ironkeep.lua yet")) return "Nog geen meting. Log uit of typ /reload, en klik daarna op Vernieuwen.";
            if (message.StartsWith("No Ironkeep.lua")) return "Geen Ironkeep.lua in deze map. Log uit of typ /reload, en klik daarna op Vernieuwen.";
            if (message == "This file has no Ironkeep list.") return "Dit bestand heeft geen Ironkeep-lijst.";
            if (message == "This saved file could not be read.") return "Dit bestand kon niet gelezen worden.";
            if (message == "This saved file is cut off.") return "Dit bestand is afgekapt.";
            if (message == "The built-in sample is missing.") return "Het ingebouwde voorbeeld ontbreekt.";
            return message;
        }

        static Color ClassColor(string classFile, string className)
        {
            string key = classFile;
            if (key == null || key.Length == 0) key = className ?? "";
            switch (key.ToUpperInvariant())
            {
                case "WARRIOR": return Color.FromArgb(199, 156, 110);
                case "PALADIN": return Color.FromArgb(245, 140, 186);
                case "HUNTER": return Color.FromArgb(171, 212, 115);
                case "ROGUE": return Color.FromArgb(255, 245, 105);
                case "PRIEST": return Color.FromArgb(255, 255, 255);
                case "SHAMAN": return Color.FromArgb(0, 112, 222);
                case "MAGE": return Color.FromArgb(105, 204, 240);
                case "WARLOCK": return Color.FromArgb(148, 130, 201);
                case "DRUID": return Color.FromArgb(255, 125, 10);
                default: return TextMain;
            }
        }

        static Font UiFont(float size, FontStyle style)
        {
            try { return new Font("Segoe UI", size, style, GraphicsUnit.Point); }
            catch (ArgumentException) { return new Font(FontFamily.GenericSansSerif, size, style, GraphicsUnit.Point); }
        }

        static Font MonoFont(float size)
        {
            try { return new Font("Consolas", size, FontStyle.Regular, GraphicsUnit.Point); }
            catch (ArgumentException) { return new Font(FontFamily.GenericMonospace, size, FontStyle.Regular, GraphicsUnit.Point); }
        }
    }
}
