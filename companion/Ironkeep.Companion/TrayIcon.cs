using System;
using System.Drawing;
using System.Windows.Forms;

namespace Ironkeep.Companion
{
    static class TrayIcon
    {
        public static NotifyIcon Create(MainWindow window, CompanionSession session, Action quit)
        {
            var actions = new TrayActions(
                delegate { window.Dispatcher.BeginInvoke(new Action(window.BringForward)); },
                delegate { window.Dispatcher.BeginInvoke(new Action(window.RunSync)); },
                delegate { window.Dispatcher.BeginInvoke(new Action(delegate { MainWindow.OpenSite(session); })); },
                delegate { window.Dispatcher.BeginInvoke(new Action(quit)); });
            var icon = new NotifyIcon();
            icon.Text = "Ironkeep Companion";
            icon.Icon = LoadIcon();
            icon.Visible = true;
            var menu = new ContextMenuStrip();
            menu.Items.Add("Open", null, delegate { actions.Open(); });
            menu.Items.Add("Sync now", null, delegate { actions.Sync(); });
            menu.Items.Add("Open website", null, delegate { actions.Website(); });
            menu.Items.Add("Quit", null, delegate { actions.Quit(); });
            icon.ContextMenuStrip = menu;
            icon.DoubleClick += delegate { actions.Open(); };
            return icon;
        }

        static Icon LoadIcon()
        {
            try
            {
                string path = Environment.ProcessPath;
                if (path != null && path.Length > 0)
                {
                    Icon associated = Icon.ExtractAssociatedIcon(path);
                    if (associated != null) return associated;
                }
            }
            catch (Exception)
            {
            }
            return SystemIcons.Application;
        }
    }
}
