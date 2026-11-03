using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
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
        readonly Button copyButton;
        readonly Button sampleButton;
        readonly Label hintLabel = new Label();
        readonly Label statusLabel = new Label();
        MemoryStream logoStream;
        string reportText = "";

        public MainWindow()
        {
            Text = "Ironkeep Companion";
            Font = UiFont(10f, FontStyle.Regular);
            BackColor = Bg;
            ForeColor = TextMain;
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(760, 520);
            ClientSize = new Size(880, 580);
            DoubleBuffered = true;
            KeyPreview = true;

            browseButton = MakeButton("Kies map", false);
            refreshButton = MakeButton("Vernieuwen", true);
            copyButton = MakeButton("Kopieer lijst", true);
            sampleButton = MakeButton("Voorbeeld", false);
            copyButton.Enabled = false;

            StylePanel(brand, 72, DockStyle.Top);
            StylePanel(pathRow, 48, DockStyle.Top);
            StylePanel(meta, 58, DockStyle.Top);
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

            StyleLabel(hintLabel, "Er wordt niets naar de site gestuurd.", Muted, 9.5f, FontStyle.Regular);
            StyleLabel(statusLabel, "", Muted, 9f, FontStyle.Regular);

            browseButton.Click += BrowseClick;
            refreshButton.Click += RefreshClick;
            copyButton.Click += CopyClick;
            sampleButton.Click += SampleClick;

            brand.Controls.Add(logo);
            brand.Controls.Add(titleLabel);
            brand.Controls.Add(subtitleLabel);
            pathRow.Controls.Add(pathBox);
            pathRow.Controls.Add(browseButton);
            pathRow.Controls.Add(refreshButton);
            meta.Controls.Add(placeLabel);
            meta.Controls.Add(detailLabel);
            meta.Controls.Add(countLabel);
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
            Controls.Add(meta);
            Controls.Add(pathRow);
            Controls.Add(brand);

            brand.Resize += delegate { LayoutChrome(); };
            pathRow.Resize += delegate { LayoutChrome(); };
            meta.Resize += delegate { LayoutChrome(); };
            bottom.Resize += delegate { LayoutChrome(); };
            LoadLogo();
            LayoutChrome();
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
            if (saved.Length > 0 && TryFolder(saved)) return;
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
            try
            {
                string file = Saved.FindSaved(folder);
                ApplyFile(file, Saved.LoadPath(file));
                return true;
            }
            catch (SavedException ex)
            {
                if (ex.Message.StartsWith("No Ironkeep.lua")) return false;
                ClearGroup();
                SetStatus(Dutch(ex.Message), Warning);
                return true;
            }
        }

        void ApplyFile(string file, Dictionary<object, object> db)
        {
            string root = WowRoot(file);
            pathBox.Text = root.Length > 0 ? root : Path.GetDirectoryName(file);
            Remember(pathBox.Text);
            string when = File.GetLastWriteTime(file).ToString("yyyy-MM-dd HH:mm");
            ShowGroup(Saved.Describe(db), AccountOf(file), "Gelezen uit " + file + "    " + when, Muted);
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
