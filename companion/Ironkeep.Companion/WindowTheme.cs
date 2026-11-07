using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace Ironkeep.Companion
{
    static class WindowTheme
    {
        const int UseImmersiveDarkMode = 20;

        public static void UseDarkCaption(Window window)
        {
            window.SourceInitialized += delegate
            {
                try
                {
                    IntPtr handle = new WindowInteropHelper(window).Handle;
                    int enabled = 1;
                    DwmSetWindowAttribute(handle, UseImmersiveDarkMode, ref enabled, sizeof(int));
                }
                catch (Exception)
                {
                }
            };
        }

        [DllImport("dwmapi.dll")]
        static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
    }
}
